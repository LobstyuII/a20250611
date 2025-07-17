import os
import ftplib
import logging
import datetime
import time
import pandas as pd
import numpy as np
import netCDF4 as nc
import xarray as xr
from concurrent.futures import ThreadPoolExecutor, as_completed
import glob
import json
import sys
import csv
import threading


# 自定义日志过滤器 - 允许非warning级别的日志通过
class NotWarningFilter(logging.Filter):
    def filter(self, record):
        return record.levelno != logging.WARNING


# 设置日志配置
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 文件日志处理器
file_handler = logging.FileHandler('h8l3par_download.log')
file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# 终端日志处理器
console_handler = logging.StreamHandler(sys.stdout)
console_formatter = logging.Formatter('%(asctime)s - %(message)s')
console_handler.setFormatter(console_formatter)
console_handler.addFilter(NotWarningFilter())  # 过滤掉warning级别的日志
logger.addHandler(console_handler)

# FTP密钥文件
CONFIG_FILE = "ftp_config#1.json"


def load_ftp_config():
    """从JSON文件加载FTP配置"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        return config
    except FileNotFoundError:
        logger.error(f"配置文件不存在: {CONFIG_FILE}")
        raise
    except json.JSONDecodeError:
        logger.error(f"配置文件格式错误: {CONFIG_FILE}")
        raise
    except Exception as e:
        logger.error(f"读取配置文件失败: {e}")
        raise


# 加载FTP配置
try:
    FTP_CONFIG = load_ftp_config()
    FTP_ADDRESS = FTP_CONFIG["FTP_ADDRESS"]
    FTP_UID = FTP_CONFIG["FTP_UID"]
    FTP_PW = FTP_CONFIG["FTP_PW"]
except Exception as e:
    logger.critical("无法加载FTP配置，程序终止")
    exit(1)

# 全局锁和缺失文件记录
vacant_lock = threading.Lock()
vacant_dates = set()
vacant_file_path = None


def record_vacant_date(date_str):
    """记录缺失文件日期到CSV（线程安全）"""
    global vacant_dates, vacant_file_path

    with vacant_lock:
        if date_str not in vacant_dates:
            vacant_dates.add(date_str)
            try:
                # 使用追加模式写入
                with open(vacant_file_path, 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([date_str])
                logger.warning(f"记录缺失文件: {date_str}")
            except Exception as e:
                logger.error(f"写入缺失文件记录失败: {e}")


def download_from_ftp(ftp_path, local_filename, download_dir):
    """从FTP服务器下载文件，当文件不存在时立即返回"""
    logger.info(f"尝试从FTP服务器下载文件: {ftp_path}")

    # 创建下载目录
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    final_filepath = os.path.join(download_dir, local_filename)

    try:
        # 建立FTP连接
        with ftplib.FTP(FTP_ADDRESS, timeout=30) as ftp:
            ftp.login(FTP_UID, FTP_PW)
            ftp.voidcmd("TYPE I")

            # 检查文件是否存在
            try:
                file_size = ftp.size(ftp_path)
            except ftplib.error_perm as e:
                # 550错误表示文件不存在
                if '550' in str(e):
                    logger.warning(f"文件在FTP上不存在: {ftp_path}")
                    return None
                raise  # 其他权限错误继续抛出

            # 文件存在，开始下载
            temp_filepath = os.path.join(download_dir, f"temp_{local_filename}")

            # 检查并删除临时文件（如果存在）
            if os.path.exists(temp_filepath):
                logger.info(f"发现临时文件 {temp_filepath}，删除它并重新下载")
                os.remove(temp_filepath)

            with open(temp_filepath, 'wb') as local_file:
                def callback(data):
                    local_file.write(data)

                # 从头开始下载（rest=0）
                ftp.retrbinary(f'RETR {ftp_path}', callback, rest=0)

            # 确认文件下载成功
            if os.path.getsize(temp_filepath) == file_size:
                os.rename(temp_filepath, final_filepath)
                logger.info(f"文件下载成功: {final_filepath}")
                return final_filepath
            else:
                os.remove(temp_filepath)
                raise Exception("下载文件大小不匹配")

    except ftplib.all_errors as e:
        logger.error(f"FTP文件下载失败: {e}")
    except Exception as e:
        logger.error(f"未知错误: {e}")
    finally:
        # 确保删除临时文件（如果存在）
        temp_filepath = os.path.join(download_dir, f"temp_{local_filename}")
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)

    return None


def process_l3par_file_to_nc(l3par_file_path, lookup_df, output_path):
    """处理L3 PAR文件并保存为.nc数据集"""
    try:
        # 创建输出文件
        with nc.Dataset(output_path, 'w', format='NETCDF4') as ds_out:
            # 创建维度
            ds_out.createDimension('Station', len(lookup_df))

            # 创建变量
            station_var = ds_out.createVariable('Station', str, ('Station',))
            par_var = ds_out.createVariable('PAR', 'f4', ('Station',))
            swr_var = ds_out.createVariable('SWR', 'f4', ('Station',))

            # 添加时间属性
            filename = os.path.basename(l3par_file_path)
            # 文件名格式: H08_YYYYMMDD_HH00_1H_*.nc
            time_str = filename.split('_')[2]  # 获取时间部分 (0900)
            ds_out.setncattr('time', time_str[:2] + ':' + time_str[2:])  # 格式化为 HH:MM

            # 打开输入文件
            with nc.Dataset(l3par_file_path, 'r') as dataset:
                # 获取PAR变量及其属性
                par_var_in = dataset.variables['PAR']
                par_scale = par_var_in.scale_factor
                par_offset = par_var_in.add_offset
                par_missing = par_var_in.missing_value

                # 获取SWR变量及其属性
                swr_var_in = dataset.variables['SWR']
                swr_scale = swr_var_in.scale_factor
                swr_offset = swr_var_in.add_offset
                swr_missing = swr_var_in.missing_value

                # 初始化列表
                station_names = []
                par_values = []
                swr_values = []

                # 遍历每个站点，提取数据
                for _, row in lookup_df.iterrows():
                    station_name = row['Station']
                    h8_x = int(row['H8L1_x'])
                    h8_y = int(row['H8L1_y'])

                    # 读取原始PAR值
                    raw_par = par_var_in[h8_y, h8_x]
                    # 处理缺失值
                    if raw_par == par_missing:
                        par_value = np.nan
                    else:
                        # 转换为实际值
                        par_value = raw_par * par_scale + par_offset

                    # 读取原始SWR值
                    raw_swr = swr_var_in[h8_y, h8_x]
                    # 处理缺失值
                    if raw_swr == swr_missing:
                        swr_value = np.nan
                    else:
                        # 转换为实际值
                        swr_value = raw_swr * swr_scale + swr_offset

                    station_names.append(station_name)
                    par_values.append(par_value)
                    swr_values.append(swr_value)

            # 写入数据
            station_var[:] = np.array(station_names, dtype='S')
            par_var[:] = np.array(par_values, dtype=np.float32)
            swr_var[:] = np.array(swr_values, dtype=np.float32)

            # 添加变量属性
            par_var.long_name = 'Photosynthetically active radiation'
            par_var.units = 'umol/m^2/s'
            par_var.missing_value = np.nan

            swr_var.long_name = 'Shortwave radiation'
            swr_var.units = 'W/m^2'
            swr_var.missing_value = np.nan

        logger.info(f"成功处理并保存小文件: {output_path}")
        return True
    except Exception as e:
        logger.error(f"处理文件失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def download_and_process_l3(date, hour, lookup_df, base_dir):
    """下载并处理单个L3文件"""
    global vacant_file_path

    # 创建月份文件夹
    month_dir = os.path.join(base_dir, "H8L3PAR", f"{date.year:04d}", f"{date.month:02d}")
    os.makedirs(month_dir, exist_ok=True)

    # 确定卫星前缀（2022年12月13日0000之后使用H09）
    satellite_prefix = "H09" if date >= datetime.date(2022, 12, 13) else "H08"

    # 设置文件名和路径
    ftp_path = (f"/pub/himawari/L3/PAR/021/{date.year:04d}{date.month:02d}/"
                f"{date.day:02d}/"
                f"{satellite_prefix}_{date.year:04d}{date.month:02d}{date.day:02d}_{hour:02d}00_1H_RFL021_FLDK.02401_02401.nc")

    # 本地文件名
    local_filename = f"{satellite_prefix}_{date.year:04d}{date.month:02d}{date.day:02d}_{hour:02d}00.nc"
    local_filepath = os.path.join(month_dir, local_filename)

    # 输出小文件名
    small_nc_filename = f"H8L3PAR_{date.year:04d}{date.month:02d}{date.day:02d}_{hour:02d}00.nc"
    small_nc_path = os.path.join(month_dir, small_nc_filename)

    # 检查小文件是否已存在
    if os.path.exists(small_nc_path):
        logger.info(f"小文件已存在: {small_nc_path}，跳过处理")
        return small_nc_path

    # 下载文件
    downloaded_file = download_from_ftp(ftp_path, local_filename, month_dir)

    # 处理文件缺失情况
    if downloaded_file is None:
        # 生成日期字符串格式：YYYYMMDD_HH00
        date_str = f"{date.year:04d}{date.month:02d}{date.day:02d}_{hour:02d}00"
        record_vacant_date(date_str)
        return None

    # 如果文件下载成功，则处理文件
    if downloaded_file:
        success = process_l3par_file_to_nc(downloaded_file, lookup_df, small_nc_path)
        if success:
            logger.info(f"文件处理完成: {downloaded_file}")
            # 删除下载的原始数据文件
            os.remove(downloaded_file)
            logger.info(f"已删除下载的原始数据文件: {downloaded_file}")
            return small_nc_path

    return None


def integrate_monthly_data_l3(month_dir, year, month):
    """整合月度数据 - 使用增量写入方式（不删除小文件）"""
    # 查找所有小文件
    small_files = glob.glob(os.path.join(month_dir, "H8L3PAR_*.nc"))
    if not small_files:
        logger.warning(f"在目录 {month_dir} 中未找到小文件")
        return None

    # 按月排序文件
    small_files.sort()

    # 月度数据集输出路径
    output_path = os.path.join(month_dir, f"H8L3PAR_monthly_{year:04d}{month:02d}.nc")

    # 如果月度文件已存在，跳过处理
    if os.path.exists(output_path):
        logger.info(f"月度数据集已存在: {output_path}，跳过整合")
        return output_path

    logger.info(f"开始整合 {year:04d}-{month:02d} 的 {len(small_files)} 个小文件")

    # 创建空的月度数据集文件
    with nc.Dataset(output_path, 'w', format='NETCDF4') as ds_out:
        # 初始化维度
        ds_out.createDimension('time', None)  # 无限维度
        ds_out.createDimension('Station', None)  # 无限维度

        # 创建变量
        time_var = ds_out.createVariable('time', 'f8', ('time',))
        station_var = ds_out.createVariable('Station', str, ('Station',))
        par_var = ds_out.createVariable('PAR', 'f4', ('time', 'Station'))
        swr_var = ds_out.createVariable('SWR', 'f4', ('time', 'Station'))

        # 添加变量属性
        par_var.long_name = 'Photosynthetically active radiation'
        par_var.units = 'umol/m^2/s'
        par_var.missing_value = np.nan

        swr_var.long_name = 'Shortwave radiation'
        swr_var.units = 'W/m^2'
        swr_var.missing_value = np.nan

        # 初始化索引
        time_index = 0
        station_names = None
        station_count = 0

        # 处理每个小文件
        for i, file_path in enumerate(small_files):
            if (i + 1) % 24 == 0:  # 每24个文件报告一次进度
                logger.info(f"整合进度: {i + 1}/{len(small_files)}")

            try:
                # 从文件名提取时间
                filename = os.path.basename(file_path)
                # 文件名格式: H8L3PAR_YYYYMMDD_HH00.nc
                time_str = filename.split('_')[1] + filename.split('_')[2].split('.')[0]
                dt = datetime.datetime.strptime(time_str, "%Y%m%d%H00")
                time_value = (dt - datetime.datetime(1970, 1, 1)).total_seconds()

                with nc.Dataset(file_path, 'r') as ds_small:
                    # 处理站点名称（可能是字符串或字节）
                    station_data = ds_small['Station'][:]
                    if isinstance(station_data[0], bytes):
                        current_stations = [s.decode('utf-8') for s in station_data]
                    else:
                        current_stations = station_data.tolist()

                    # 如果是第一个文件，初始化站点信息
                    if station_names is None:
                        station_names = current_stations
                        station_count = len(station_names)
                        station_var[:] = np.array(station_names, dtype='S')

                    # 检查站点一致性
                    if current_stations != station_names:
                        logger.warning(f"文件 {filename} 的站点与前文件不一致")
                        continue

                    # 添加时间值
                    time_var[time_index] = time_value

                    # 添加数据
                    par_var[time_index, :] = ds_small['PAR'][:]
                    swr_var[time_index, :] = ds_small['SWR'][:]

                    time_index += 1

            except Exception as e:
                logger.error(f"处理小文件 {file_path} 失败: {e}")
                import traceback
                logger.error(traceback.format_exc())

        # 添加时间属性
        time_var.units = 'seconds since 1970-01-01 00:00:00'
        time_var.calendar = 'standard'

    logger.info(f"月度数据集已保存: {output_path}")

    return output_path


def main_l3():
    global vacant_file_path, vacant_dates

    # 基础数据路径
    Data_path = r"D:\H8_data"

    # 使用LUTs.nc查找表
    lut_path = os.path.join(Data_path, "LUTs.nc")
    if not os.path.exists(lut_path):
        logger.error(f"查找表文件不存在: {lut_path}")
        return

    # 从NetCDF文件加载查找表
    try:
        with xr.open_dataset(lut_path) as ds:
            lookup_df = pd.DataFrame({
                'Station': ds['Station'].values,
                'H8L1_x': ds['H8L1_x'].values,
                'H8L1_y': ds['H8L1_y'].values
            })
        logger.info(f"成功加载查找表，包含 {len(lookup_df)} 个站点")
    except Exception as e:
        logger.error(f"加载查找表失败: {e}")
        return

    # 缺失文件记录路径
    h8l3par_base_dir = os.path.join(Data_path, "H8L3PAR")
    os.makedirs(h8l3par_base_dir, exist_ok=True)
    vacant_file_path = os.path.join(h8l3par_base_dir, "H8L3PAR_vacant.csv")

    # 加载已有的缺失记录
    if os.path.exists(vacant_file_path):
        try:
            with open(vacant_file_path, 'r') as f:
                reader = csv.reader(f)
                for row in reader:
                    if row:  # 跳过空行
                        vacant_dates.add(row[0])
            logger.info(f"已加载 {len(vacant_dates)} 条缺失文件记录")
        except Exception as e:
            logger.error(f"加载缺失文件记录失败: {e}")
    else:
        # 创建新的CSV文件并写入标题
        with open(vacant_file_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["vacant_date"])
        logger.info("创建新的缺失文件记录")

    # 设置日期范围和时间（每小时一次）
    start_date = datetime.date(2015, 7, 7)  # 从2015年7月7日开始
    end_date = datetime.date(2021, 12, 31)  # 可根据需要调整结束日期
    hours = [*range(0, 13), *range(21, 24)]  # 0-23小时

    # 按月份处理
    current_date = start_date
    while current_date <= end_date:
        year = current_date.year
        month = current_date.month

        # 创建月份文件夹
        month_dir = os.path.join(h8l3par_base_dir, f"{year:04d}", f"{month:02d}")
        os.makedirs(month_dir, exist_ok=True)

        logger.info(f"开始处理 {year:04d}-{month:02d} 的L3数据")

        # 准备当前月的任务
        tasks = []
        temp_date = current_date.replace(day=1)  # 从当月1号开始
        while temp_date.month == month and temp_date <= end_date:
            # 跳过7月1-6日的数据（只从7月7日开始）
            if year == 2015 and month == 7 and temp_date.day < 7:
                temp_date += datetime.timedelta(days=1)
                continue

            for hour in hours:
                tasks.append((temp_date, hour))
            temp_date += datetime.timedelta(days=1)

        # 使用线程池并行下载和处理
        futures = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            for date, hour in tasks:
                future = executor.submit(
                    download_and_process_l3, date, hour, lookup_df, Data_path
                )
                futures.append(future)

            # 等待所有任务完成
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"任务执行失败: {e}")

        # 整合月度数据
        integrate_monthly_data_l3(month_dir, year, month)

        # 移动到下个月
        if month == 12:
            current_date = datetime.date(year + 1, 1, 1)
        else:
            current_date = datetime.date(year, month + 1, 1)

    logger.info("所有月份处理完成")
    logger.info(f"总共缺失 {len(vacant_dates)} 个文件，记录在: {vacant_file_path}")


if __name__ == "__main__":
    main_l3()