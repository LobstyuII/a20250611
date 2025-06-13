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

# 设置日志配置
logging.basicConfig(filename='h8l1_download#2.log', level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# FTP密钥文件
CONFIG_FILE = "ftp_config#2.json"

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

def download_from_ftp(ftp_path, local_filename, download_dir, max_retries=5, retry_delay=10):
    """从FTP服务器下载文件，支持断点续传"""
    logger.info(f"开始从FTP服务器下载文件: {ftp_path}")

    # 创建下载目录
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    temp_filepath = os.path.join(download_dir, f"temp_{local_filename}")
    final_filepath = os.path.join(download_dir, local_filename)
    resume_byte_pos = 0

    # 如果文件已存在，检查文件大小用于断点续传
    if os.path.exists(final_filepath):
        resume_byte_pos = os.path.getsize(final_filepath)
        logger.info(f"文件已存在，准备从 {resume_byte_pos} 字节处继续下载。")

    attempt = 0
    start_time = time.time()  # 记录连接开始时间

    while attempt < max_retries:
        try:
            # 建立FTP连接
            with ftplib.FTP(FTP_ADDRESS, timeout=retry_delay) as ftp:
                ftp.login(FTP_UID, FTP_PW)
                ftp.voidcmd("TYPE I")
                file_size = ftp.size(ftp_path)

                # 如果文件已完整下载
                if resume_byte_pos >= file_size:
                    logger.info("文件已完整下载，无需重新下载。")
                    return final_filepath

                # 打开临时文件，以写入模式（'wb'）写入
                with open(temp_filepath, 'wb') as local_file:
                    def callback(data):
                        local_file.write(data)

                    # 重新开始下载并使用断点续传
                    ftp.retrbinary(f'RETR {ftp_path}', callback, rest=resume_byte_pos)

                # 确认文件下载成功
                if os.path.getsize(temp_filepath) == file_size:
                    os.rename(temp_filepath, final_filepath)
                    logger.info(f"文件下载成功: {final_filepath}")
                    return final_filepath
                else:
                    os.remove(temp_filepath)
                    raise Exception("下载文件大小不匹配")

        except ftplib.all_errors as e:
            logger.warning(f"FTP文件下载失败: {e}, 重试 {attempt + 1}/{max_retries}...")
            attempt += 1
            time.sleep(retry_delay)
        except Exception as e:
            logger.error(f"未知错误: {e}")
            break

    logger.error(f"文件下载失败: 超过最大重试次数 {max_retries}")
    return None


def process_l1_file_to_small_nc(l1_file_path, lookup_df, output_path):
    """处理NetCDF文件并保存为小型数据集"""
    try:
        with nc.Dataset(l1_file_path, 'r') as dataset:
            # 获取所需变量
            albedo_01 = dataset.variables['albedo_01'][:]
            albedo_02 = dataset.variables['albedo_02'][:]
            albedo_03 = dataset.variables['albedo_03'][:]
            albedo_04 = dataset.variables['albedo_04'][:]
            albedo_05 = dataset.variables['albedo_05'][:]
            albedo_06 = dataset.variables['albedo_06'][:]
            saz = dataset.variables['SAZ'][:]
            saa = dataset.variables['SAA'][:]
            soz = dataset.variables['SOZ'][:]
            soa = dataset.variables['SOA'][:]

            # 创建小型数据集
            with nc.Dataset(output_path, 'w', format='NETCDF4') as ds_out:
                # 创建维度
                ds_out.createDimension('Station', len(lookup_df))

                # 创建变量
                station_var = ds_out.createVariable('Station', str, ('Station',))
                albedo_01_var = ds_out.createVariable('Albedo_01', 'f4', ('Station',))
                albedo_02_var = ds_out.createVariable('Albedo_02', 'f4', ('Station',))
                albedo_03_var = ds_out.createVariable('Albedo_03', 'f4', ('Station',))
                albedo_04_var = ds_out.createVariable('Albedo_04', 'f4', ('Station',))
                albedo_05_var = ds_out.createVariable('Albedo_05', 'f4', ('Station',))
                albedo_06_var = ds_out.createVariable('Albedo_06', 'f4', ('Station',))
                saz_var = ds_out.createVariable('SAZ', 'f4', ('Station',))
                saa_var = ds_out.createVariable('SAA', 'f4', ('Station',))
                soz_var = ds_out.createVariable('SOZ', 'f4', ('Station',))
                soa_var = ds_out.createVariable('SOA', 'f4', ('Station',))

                # 添加时间属性
                ds_out.setncattr('time', os.path.basename(output_path).split('_')[2].split('.')[0])

                # 填充数据
                station_names = []
                albedos_01 = []
                albedos_02 = []
                albedos_03 = []
                albedos_04 = []
                albedos_05 = []
                albedos_06 = []
                sazs = []
                saas = []
                sozs = []
                soas = []

                # 遍历每个站点，提取数据
                for _, row in lookup_df.iterrows():
                    station_name = row['Station']
                    h8l1_x = int(row['H8L1_x'])
                    h8l1_y = int(row['H8L1_y'])

                    # 计算反照率除以cos(SOZ)
                    soz_val = soz[h8l1_y, h8l1_x]
                    soz_rad = np.deg2rad(soz_val)
                    cos_soz = np.cos(soz_rad)

                    # 处理可能的除零错误
                    if cos_soz <= 0.01:
                        cos_soz = 0.01

                    # 提取并校正反照率
                    albedos = [
                        albedo_01[h8l1_y, h8l1_x] / cos_soz,
                        albedo_02[h8l1_y, h8l1_x] / cos_soz,
                        albedo_03[h8l1_y, h8l1_x] / cos_soz,
                        albedo_04[h8l1_y, h8l1_x] / cos_soz,
                        albedo_05[h8l1_y, h8l1_x] / cos_soz,
                        albedo_06[h8l1_y, h8l1_x] / cos_soz
                    ]

                    # 提取角度值
                    angles = [
                        saz[h8l1_y, h8l1_x],
                        saa[h8l1_y, h8l1_x],
                        soz_val,
                        soa[h8l1_y, h8l1_x]
                    ]

                    station_names.append(station_name)
                    albedos_01.append(albedos[0])
                    albedos_02.append(albedos[1])
                    albedos_03.append(albedos[2])
                    albedos_04.append(albedos[3])
                    albedos_05.append(albedos[4])
                    albedos_06.append(albedos[5])
                    sazs.append(angles[0])
                    saas.append(angles[1])
                    sozs.append(angles[2])
                    soas.append(angles[3])

                # 写入数据
                station_var[:] = np.array(station_names, dtype='S')
                albedo_01_var[:] = np.array(albedos_01, dtype=np.float32)
                albedo_02_var[:] = np.array(albedos_02, dtype=np.float32)
                albedo_03_var[:] = np.array(albedos_03, dtype=np.float32)
                albedo_04_var[:] = np.array(albedos_04, dtype=np.float32)
                albedo_05_var[:] = np.array(albedos_05, dtype=np.float32)
                albedo_06_var[:] = np.array(albedos_06, dtype=np.float32)
                saz_var[:] = np.array(sazs, dtype=np.float32)
                saa_var[:] = np.array(saas, dtype=np.float32)
                soz_var[:] = np.array(sozs, dtype=np.float32)
                soa_var[:] = np.array(soas, dtype=np.float32)

            logger.info(f"成功处理并保存小文件: {output_path}")
            return True
    except Exception as e:
        logger.error(f"处理文件失败: {e}")
        return False


def download_and_process(date, hour, minute, lookup_df, base_dir):
    """下载并处理单个文件"""
    # 创建月份文件夹 - 修改路径包含H8L1
    month_dir = os.path.join(base_dir, "H8L1", f"{date.year:04d}", f"{date.month:02d}")
    os.makedirs(month_dir, exist_ok=True)

    # 设置文件名和路径
    ftp_path = f"/jma/netcdf/{date.year:04d}{date.month:02d}/{date.day:02d}/NC_H08_{date.year:04d}{date.month:02d}{date.day:02d}_{hour:02d}{minute:02d}_R21_FLDK.02401_02401.nc"
    local_filename = f"himawari_{date.strftime('%Y%m%d')}_{hour:02d}{minute:02d}.nc"
    local_filepath = os.path.join(month_dir, local_filename)

    # 输出小文件名
    small_nc_filename = f"H8_{date.year:04d}{date.month:02d}{date.day:02d}_{hour:02d}{minute:02d}.nc"
    small_nc_path = os.path.join(month_dir, small_nc_filename)

    # 检查小文件是否已存在
    if os.path.exists(small_nc_path):
        logger.info(f"小文件已存在: {small_nc_path}，跳过处理")
        return small_nc_path

    # 下载文件
    downloaded_file = download_from_ftp(ftp_path, local_filename, month_dir)

    # 如果文件下载成功，则处理文件
    if downloaded_file:
        success = process_l1_file_to_small_nc(downloaded_file, lookup_df, small_nc_path)
        if success:
            logger.info(f"文件处理完成: {downloaded_file}")
            # 删除下载的原始数据文件
            os.remove(downloaded_file)
            logger.info(f"已删除下载的原始数据文件: {downloaded_file}")
            return small_nc_path
    else:
        logger.error(f"无法下载文件: {ftp_path}")

    return None


def integrate_monthly_data(month_dir, year, month):
    """整合月度数据"""
    # 查找所有小文件
    small_files = glob.glob(os.path.join(month_dir, "H8_*.nc"))
    if not small_files:
        logger.warning(f"在目录 {month_dir} 中未找到小文件")
        return None

    # 创建月度数据集
    monthly_ds = None

    for file_path in small_files:
        try:
            with nc.Dataset(file_path, 'r') as ds_small:
                # 获取时间
                time_str = ds_small.getncattr('time')
                dt = datetime.datetime.strptime(time_str, "%Y%m%d%H%M")
                time_value = np.datetime64(dt)

                # 创建临时数据集
                ds_temp = xr.Dataset({
                    'Albedo_01': (['time', 'Station'], [ds_small['Albedo_01'][:]]),
                    'Albedo_02': (['time', 'Station'], [ds_small['Albedo_02'][:]]),
                    'Albedo_03': (['time', 'Station'], [ds_small['Albedo_03'][:]]),
                    'Albedo_04': (['time', 'Station'], [ds_small['Albedo_04'][:]]),
                    'Albedo_05': (['time', 'Station'], [ds_small['Albedo_05'][:]]),
                    'Albedo_06': (['time', 'Station'], [ds_small['Albedo_06'][:]]),
                    'SAZ': (['time', 'Station'], [ds_small['SAZ'][:]]),
                    'SAA': (['time', 'Station'], [ds_small['SAA'][:]]),
                    'SOZ': (['time', 'Station'], [ds_small['SOZ'][:]]),
                    'SOA': (['time', 'Station'], [ds_small['SOA'][:]])
                }, coords={
                    'time': [time_value],
                    'Station': [s.decode() for s in ds_small['Station'][:]]
                })

                # 合并到月度数据集
                if monthly_ds is None:
                    monthly_ds = ds_temp
                else:
                    monthly_ds = xr.concat([monthly_ds, ds_temp], dim='time')

        except Exception as e:
            logger.error(f"处理小文件 {file_path} 失败: {e}")

    # 保存月度数据集
    if monthly_ds is not None:
        output_path = os.path.join(month_dir, f"H8_monthly_{year:04d}{month:02d}.nc")
        monthly_ds.to_netcdf(output_path)
        logger.info(f"月度数据集已保存: {output_path}")

        # 删除小文件
        for file_path in small_files:
            os.remove(file_path)
        logger.info(f"已删除 {len(small_files)} 个小文件")

        return output_path

    return None


def main():
    Data_path = "D:/H8_data"
    LUTs_file = os.path.join(Data_path, "LUTs.nc")
    ds_lut = xr.open_dataset(LUTs_file)

    # 创建查找表DataFrame
    lookup_df = pd.DataFrame({
        'Station': ds_lut['Station'].values,
        'H8L1_x': ds_lut['H8L1_x'].values,
        'H8L1_y': ds_lut['H8L1_y'].values
    })

    # 设置日期范围和时间
    start_date = datetime.date(2017, 1, 1)
    end_date = datetime.date(2021, 12, 31)
    hours = list(range(0, 23))  # 00:00 - 22:00 UTC
    minutes = [0, 10, 20, 30, 40, 50]

    # 创建H8L1基础目录
    h8l1_base_dir = os.path.join(Data_path, "H8L1")
    os.makedirs(h8l1_base_dir, exist_ok=True)

    # 按月份处理 - 修正日期处理逻辑
    current_date = start_date
    while current_date <= end_date:
        year = current_date.year
        month = current_date.month

        # 创建月份文件夹
        month_dir = os.path.join(h8l1_base_dir, f"{year:04d}", f"{month:02d}")
        os.makedirs(month_dir, exist_ok=True)

        logger.info(f"开始处理 {year:04d}-{month:02d} 的数据")

        # 准备当前月的任务
        tasks = []
        temp_date = current_date.replace(day=1)  # 从当月1号开始
        while temp_date.month == month and temp_date <= end_date:
            # 跳过7月1-6日的数据（只从7月7日开始）
            if year == 2015 and month == 7 and temp_date.day < 7:
                temp_date += datetime.timedelta(days=1)
                continue

            for hour in hours:
                for minute in minutes:
                    tasks.append((temp_date, hour, minute))
            temp_date += datetime.timedelta(days=1)

        # 使用线程池并行下载和处理
        futures = []
        with ThreadPoolExecutor(max_workers=28) as executor:
            for date, hour, minute in tasks:
                future = executor.submit(
                    download_and_process, date, hour, minute, lookup_df, Data_path
                )
                futures.append(future)

            # 等待所有任务完成
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"任务执行失败: {e}")

        # 整合月度数据
        integrate_monthly_data(month_dir, year, month)

        # 移动到下个月
        if month == 12:
            current_date = datetime.date(year + 1, 1, 1)
        else:
            current_date = datetime.date(year, month + 1, 1)

    logger.info("所有月份处理完成")


if __name__ == "__main__":
    main()