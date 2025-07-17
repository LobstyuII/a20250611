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
file_handler = logging.FileHandler('h8_downloader.log')
file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# 终端日志处理器
console_handler = logging.StreamHandler(sys.stdout)
console_formatter = logging.Formatter('%(asctime)s - %(message)s')
console_handler.setFormatter(console_formatter)
console_handler.addFilter(NotWarningFilter())  # 过滤掉warning级别的日志
logger.addHandler(console_handler)

# 全局锁和缺失文件记录
vacant_lock = threading.Lock()
vacant_dates = set()
vacant_file_path = None
FTP_CONFIG = None
FTP_ADDRESS = None
FTP_UID = None
FTP_PW = None
DATA_TYPE = None
DATA_PATH = None
MAX_WORKERS = 20
DATE_RANGE = None


def load_ftp_configs():
    """从JSON文件加载所有FTP配置"""
    config_file = "ftp_configs.json"
    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"配置文件不存在: {config_file}")
        return {}
    except json.JSONDecodeError:
        logger.error(f"配置文件格式错误: {config_file}")
        return {}
    except Exception as e:
        logger.error(f"读取配置文件失败: {e}")
        return {}


def select_ftp_account(configs):
    """让用户选择FTP账号"""
    print("可用的FTP账号:")
    for i, key in enumerate(configs.keys(), 1):
        print(f"{i}. {key}")

    while True:
        try:
            choice = int(input("请选择要使用的FTP账号(1-3): "))
            if 1 <= choice <= len(configs):
                account_name = list(configs.keys())[choice - 1]
                return configs[account_name]
            print("输入无效，请重新输入")
        except ValueError:
            print("请输入有效数字")


def select_data_type():
    """让用户选择数据类型"""
    print("请选择要下载的数据类型:")
    print("1. L1-TOA (Top of Atmosphere)")
    print("2. L2-ARP (Aerosol Retrieval Product)")
    print("3. L3-PAR (Photosynthetically Active Radiation)")

    while True:
        try:
            choice = int(input("请输入选择(1-3): "))
            if choice == 1:
                return "L1"
            elif choice == 2:
                return "L2"
            elif choice == 3:
                return "L3"
            print("输入无效，请重新输入")
        except ValueError:
            print("请输入有效数字")


def get_date_range():
    """获取用户输入的日期范围"""
    default_start = "20150707"
    default_end = "20241231"

    print(f"请输入日期范围 (格式: YYYYMMDD-YYYYMMDD, 默认: {default_start}-{default_end})")
    date_input = input("日期范围: ").strip()

    if not date_input:
        return (datetime.datetime.strptime(default_start, "%Y%m%d").date(),
                datetime.datetime.strptime(default_end, "%Y%m%d").date())

    if "-" not in date_input:
        print("格式错误，使用默认日期范围")
        return (datetime.datetime.strptime(default_start, "%Y%m%d").date(),
                datetime.datetime.strptime(default_end, "%Y%m%d").date())

    start_str, end_str = date_input.split("-")
    try:
        start_date = datetime.datetime.strptime(start_str, "%Y%m%d").date()
        end_date = datetime.datetime.strptime(end_str, "%Y%m%d").date()
        return start_date, end_date
    except ValueError:
        print("日期格式错误，使用默认日期范围")
        return (datetime.datetime.strptime(default_start, "%Y%m%d").date(),
                datetime.datetime.strptime(default_end, "%Y%m%d").date())


def get_thread_count():
    """获取线程数"""
    default = 20
    print(f"请输入线程数 (1-30, 默认: {default})")
    try:
        count = int(input("线程数: ").strip())
        if 1 <= count <= 30:
            return count
        print("超出范围，使用默认值")
    except ValueError:
        print("输入无效，使用默认值")
    return default


def get_data_path():
    """获取数据存储路径"""
    default = r"D:\H8_data"
    print(f"请输入数据存储路径 (默认: {default})")
    path = input("路径: ").strip()
    return path or default


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
                logger.info(f"记录缺失文件: {date_str}")
            except Exception as e:
                logger.error(f"写入缺失文件记录失败: {e}")


def download_from_ftp(ftp_path, local_filename, download_dir):
    """从FTP服务器下载文件，当文件不存在时立即返回"""
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
                    logger.info(f"文件在FTP上不存在: {ftp_path}")
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
            try:
                os.remove(temp_filepath)
            except:
                pass

    return None


def get_satellite_prefix(date):
    """根据日期获取卫星前缀"""
    # 2022年12月13日0000之后使用H09
    return "H09" if date >= datetime.date(2022, 12, 13) else "H08"


def get_l1_ftp_path(date, hour, minute):
    """获取L1数据的FTP路径"""
    satellite_prefix = get_satellite_prefix(date)
    return (f"/jma/netcdf/{date.year:04d}{date.month:02d}/{date.day:02d}/"
            f"NC_{satellite_prefix}_{date.year:04d}{date.month:02d}{date.day:02d}_"
            f"{hour:02d}{minute:02d}_R21_FLDK.02401_02401.nc")


def get_l2_ftp_path(date, hour, minute):
    """获取L2数据的FTP路径"""
    satellite_prefix = get_satellite_prefix(date)
    return (f"/pub/himawari/L2/ARP/030/{date.year:04d}{date.month:02d}/"
            f"{date.day:02d}/{hour:02d}/"
            f"NC_{satellite_prefix}_{date.year:04d}{date.month:02d}{date.day:02d}_"
            f"{hour:02d}{minute:02d}_L2ARP030_FLDK.02401_02401.nc")


def get_l3_ftp_path(date, hour):
    """获取L3数据的FTP路径"""
    satellite_prefix = get_satellite_prefix(date)
    return (f"/pub/himawari/L3/PAR/021/{date.year:04d}{date.month:02d}/"
            f"{date.day:02d}/"
            f"{satellite_prefix}_{date.year:04d}{date.month:02d}{date.day:02d}_"
            f"{hour:02d}00_1H_RFL021_FLDK.02401_02401.nc")


def process_l1_file(l1_file_path, lookup_df, output_path):
    """处理L1文件并保存为小型数据集"""
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
                time_str = os.path.basename(l1_file_path).split('_')[2].split('.')[0]
                ds_out.setncattr('time', time_str)

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

            logger.info(f"成功处理并保存L1小文件: {output_path}")
            return True
    except Exception as e:
        logger.error(f"处理L1文件失败: {e}")
        return False


def process_l2_file(l2_file_path, lookup_df, output_path):
    """处理L2文件并保存为.nc数据集"""
    try:
        # 创建输出文件
        with nc.Dataset(output_path, 'w', format='NETCDF4') as ds_out:
            # 创建维度
            ds_out.createDimension('Station', len(lookup_df))

            # 创建变量
            station_var = ds_out.createVariable('Station', str, ('Station',))
            data_avail_var = ds_out.createVariable('Data_Availability', 'i1', ('Station',))
            land_water_var = ds_out.createVariable('Land_Water_Flag', 'i1', ('Station',))
            cloud_flag_var = ds_out.createVariable('Cloud_Flag', 'i1', ('Station',))
            aot_var = ds_out.createVariable('AOT', 'f4', ('Station',))
            aot_uncertainty_var = ds_out.createVariable('AOT_Uncertainty', 'f4', ('Station',))

            # 添加时间属性
            filename = os.path.basename(l2_file_path)
            time_str = filename.split('_')[2]  # 获取时间部分
            ds_out.setncattr('time', time_str)

            # 打开输入文件
            with nc.Dataset(l2_file_path, 'r') as dataset:
                # 获取变量
                qa_flag_var = dataset.variables['QA_flag']
                aot_var_in = dataset.variables['AOT']  # 500nm气溶胶光学厚度
                aot_uncertainty_var_in = dataset.variables['AOT_uncertainty']  # 气溶胶光学厚度不确定性

                # 初始化列表
                station_names = []
                data_avails = []
                land_waters = []
                cloud_flags = []
                aots = []
                aot_uncertainties = []

                # 遍历每个站点，提取数据
                for _, row in lookup_df.iterrows():
                    station_name = row['Station']
                    l2arp_x = int(row['L2ARP_x'])
                    l2arp_y = int(row['L2ARP_y'])

                    # 直接读取单个点的值
                    qa_value = qa_flag_var[l2arp_y, l2arp_x]
                    aot_value = aot_var_in[l2arp_y, l2arp_x]
                    aot_uncertainty_value = aot_uncertainty_var_in[l2arp_y, l2arp_x]

                    # 提取前三个比特位的值
                    data_avail = qa_value & 1
                    land_water = (qa_value >> 1) & 1
                    cloud_flag = (qa_value >> 2) & 1

                    station_names.append(station_name)
                    data_avails.append(data_avail)
                    land_waters.append(land_water)
                    cloud_flags.append(cloud_flag)
                    aots.append(aot_value)
                    aot_uncertainties.append(aot_uncertainty_value)

            # 写入数据
            station_var[:] = np.array(station_names, dtype='S')
            data_avail_var[:] = np.array(data_avails, dtype=np.int8)
            land_water_var[:] = np.array(land_waters, dtype=np.int8)
            cloud_flag_var[:] = np.array(cloud_flags, dtype=np.int8)
            aot_var[:] = np.array(aots, dtype=np.float32)
            aot_uncertainty_var[:] = np.array(aot_uncertainties, dtype=np.float32)

        logger.info(f"成功处理并保存L2小文件: {output_path}")
        return True
    except Exception as e:
        logger.error(f"处理L2文件失败: {e}")
        return False


def process_l3_file(l3_file_path, lookup_df, output_path):
    """处理L3文件并保存为.nc数据集"""
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
            filename = os.path.basename(l3_file_path)
            # 文件名格式: H08_YYYYMMDD_HH00_1H_*.nc
            time_str = filename.split('_')[2]  # 获取时间部分 (0900)
            ds_out.setncattr('time', time_str[:2] + ':' + time_str[2:])  # 格式化为 HH:MM

            # 打开输入文件
            with nc.Dataset(l3_file_path, 'r') as dataset:
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

        logger.info(f"成功处理并保存L3小文件: {output_path}")
        return True
    except Exception as e:
        logger.error(f"处理L3文件失败: {e}")
        return False


def download_and_process(date, hour, minute, lookup_df, base_dir, data_type):
    """下载并处理单个文件"""
    global vacant_file_path

    # 根据数据类型确定存储路径
    if data_type == "L1":
        data_dir = "H8L1"
        ftp_path = get_l1_ftp_path(date, hour, minute)
        time_str = f"{hour:02d}{minute:02d}"
        local_filename = f"himawari_{date.strftime('%Y%m%d')}_{time_str}.nc"
        small_nc_filename = f"H8L1_{date.year:04d}{date.month:02d}{date.day:02d}_{time_str}.nc"
        process_func = process_l1_file
    elif data_type == "L2":
        data_dir = "H8L2ARP"
        ftp_path = get_l2_ftp_path(date, hour, minute)
        time_str = f"{hour:02d}{minute:02d}"
        local_filename = f"himawari_{date.strftime('%Y%m%d')}_{time_str}.nc"
        small_nc_filename = f"H8L2ARP_{date.year:04d}{date.month:02d}{date.day:02d}_{time_str}.nc"
        process_func = process_l2_file
    else:  # L3
        data_dir = "H8L3PAR"
        ftp_path = get_l3_ftp_path(date, hour)
        time_str = f"{hour:02d}00"
        local_filename = f"himawari_{date.strftime('%Y%m%d')}_{time_str}.nc"
        small_nc_filename = f"H8L3PAR_{date.year:04d}{date.month:02d}{date.day:02d}_{time_str}.nc"
        process_func = process_l3_file

    # 创建日期文件夹
    date_dir = os.path.join(base_dir, data_dir, f"{date.year:04d}", f"{date.month:02d}")
    os.makedirs(date_dir, exist_ok=True)

    small_nc_path = os.path.join(date_dir, small_nc_filename)
    date_str = f"{date.year:04d}{date.month:02d}{date.day:02d}_{time_str}"

    # 检查小文件是否已存在
    if os.path.exists(small_nc_path):
        logger.info(f"小文件已存在: {small_nc_path}，跳过处理")
        return True

    # 检查是否已知缺失文件
    if date_str in vacant_dates:
        logger.info(f"已知缺失文件: {date_str}，跳过下载")
        return False

    # 下载文件
    downloaded_file = download_from_ftp(ftp_path, local_filename, date_dir)

    # 处理文件缺失情况
    if downloaded_file is None:
        record_vacant_date(date_str)
        return False

    # 如果文件下载成功，则处理文件
    if downloaded_file:
        success = process_func(downloaded_file, lookup_df, small_nc_path)
        if success:
            logger.info(f"文件处理完成: {downloaded_file}")
            # 删除下载的原始数据文件
            try:
                os.remove(downloaded_file)
                logger.info(f"已删除下载的原始数据文件: {downloaded_file}")
            except Exception as e:
                logger.error(f"删除文件失败: {e}")
            return True

    return False


def load_lookup_table(data_type):
    """加载查找表"""
    lut_path = os.path.join(DATA_PATH, "LUTs.nc")
    if not os.path.exists(lut_path):
        logger.error(f"查找表文件不存在: {lut_path}")
        return None

    try:
        with xr.open_dataset(lut_path) as ds:
            if data_type == "L1" or data_type == "L3":
                lookup_df = pd.DataFrame({
                    'Station': ds['Station'].values,
                    'H8L1_x': ds['H8L1_x'].values,
                    'H8L1_y': ds['H8L1_y'].values
                })
            else:  # L2
                lookup_df = pd.DataFrame({
                    'Station': ds['Station'].values,
                    'L2ARP_x': ds['L2ARP_x'].values,
                    'L2ARP_y': ds['L2ARP_y'].values
                })
        logger.info(f"成功加载查找表，包含 {len(lookup_df)} 个站点")
        return lookup_df
    except Exception as e:
        logger.error(f"加载查找表失败: {e}")
        return None


def initialize_vacant_file():
    """初始化缺失文件记录"""
    global vacant_file_path, vacant_dates

    # 根据数据类型确定目录
    if DATA_TYPE == "L1":
        data_dir = "H8L1"
    elif DATA_TYPE == "L2":
        data_dir = "H8L2ARP"
    else:  # L3
        data_dir = "H8L3PAR"

    # 确定缺失文件路径
    data_dir_path = os.path.join(DATA_PATH, data_dir)
    os.makedirs(data_dir_path, exist_ok=True)
    vacant_file_path = os.path.join(data_dir_path, f"H8{DATA_TYPE}_vacant.csv")

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


def generate_tasks(start_date, end_date, data_type):
    """生成所有任务"""
    tasks = []
    current_date = start_date

    # 确定时间范围
    if data_type == "L1" or data_type == "L2":
        hours = [*range(0, 13), *range(21, 24)]  # 0-12, 21-23
        minutes = [0, 10, 20, 30, 40, 50]
    else:  # L3
        hours = [*range(0, 13), *range(21, 24)]  # 0-12, 21-23
        minutes = [0]  # L3只有整点数据

    # 生成所有日期和时间组合
    while current_date <= end_date:
        # 跳过2015年7月1-6日的数据（只从7月7日开始）
        if current_date.year == 2015 and current_date.month == 7 and current_date.day < 7:
            current_date += datetime.timedelta(days=1)
            continue

        for hour in hours:
            for minute in minutes:
                tasks.append((current_date, hour, minute))
        current_date += datetime.timedelta(days=1)

    return tasks


def main():
    global FTP_CONFIG, FTP_ADDRESS, FTP_UID, FTP_PW, DATA_TYPE, DATA_PATH, MAX_WORKERS, DATE_RANGE

    # 加载FTP配置
    ftp_configs = load_ftp_configs()
    if not ftp_configs:
        logger.critical("没有可用的FTP配置，程序终止")
        return

    # 用户选择FTP账号
    selected_config = select_ftp_account(ftp_configs)
    FTP_CONFIG = selected_config
    FTP_ADDRESS = FTP_CONFIG["FTP_ADDRESS"]
    FTP_UID = FTP_CONFIG["FTP_UID"]
    FTP_PW = FTP_CONFIG["FTP_PW"]

    logger.info(f"使用FTP账号: {FTP_UID}")
    logger.info(f"连接FTP服务器: {FTP_ADDRESS}")

    # 用户选择数据类型
    DATA_TYPE = select_data_type()
    logger.info(f"选择的数据类型: {DATA_TYPE}")

    # 用户输入日期范围
    start_date, end_date = get_date_range()
    DATE_RANGE = (start_date, end_date)
    logger.info(f"日期范围: {start_date} 至 {end_date}")

    # 用户输入线程数
    MAX_WORKERS = get_thread_count()
    logger.info(f"线程数: {MAX_WORKERS}")

    # 用户输入数据路径
    DATA_PATH = get_data_path()
    logger.info(f"数据存储路径: {DATA_PATH}")

    # 加载查找表
    lookup_df = load_lookup_table(DATA_TYPE)
    if lookup_df is None:
        return

    # 初始化缺失文件记录
    initialize_vacant_file()

    # 生成任务
    tasks = generate_tasks(start_date, end_date, DATA_TYPE)
    logger.info(f"总共生成 {len(tasks)} 个任务")

    # 进度跟踪
    total_tasks = len(tasks)
    completed_tasks = 0
    success_count = 0
    skip_count = 0
    start_time = time.time()

    # 使用线程池并行下载和处理
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for task in tasks:
            future = executor.submit(
                download_and_process, task[0], task[1], task[2], lookup_df, DATA_PATH, DATA_TYPE
            )
            futures[future] = task

        # 进度报告
        for future in as_completed(futures):
            task = futures[future]
            date, hour, minute = task
            date_str = date.strftime("%Y%m%d")
            time_str = f"{hour:02d}{minute:02d}" if DATA_TYPE != "L3" else f"{hour:02d}00"

            try:
                result = future.result()
                if result:
                    success_count += 1
                else:
                    skip_count += 1
            except Exception as e:
                logger.error(f"任务执行失败: {date_str}_{time_str} - {e}")
                skip_count += 1

            completed_tasks += 1
            elapsed_time = time.time() - start_time
            avg_time_per_task = elapsed_time / completed_tasks if completed_tasks > 0 else 0
            remaining_tasks = total_tasks - completed_tasks
            eta = avg_time_per_task * remaining_tasks

            # 每10个任务或最后任务时报告进度
            if completed_tasks % 10 == 0 or completed_tasks == total_tasks:
                logger.info(
                    f"进度: {completed_tasks}/{total_tasks} | "
                    f"成功: {success_count} | 跳过: {skip_count} | "
                    f"用时: {elapsed_time:.1f}s | "
                    f"ETA: {eta:.1f}s"
                )

    # 最终报告
    elapsed_time = time.time() - start_time
    logger.info(f"所有任务完成! 成功: {success_count}, 跳过: {skip_count}, 总用时: {elapsed_time:.1f}秒")
    logger.info(f"缺失文件记录在: {vacant_file_path}")


if __name__ == "__main__":
    main()