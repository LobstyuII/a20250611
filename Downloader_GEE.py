import ee
import pandas as pd
import datetime
import os
import logging
import time
import numpy as np
import netCDF4 as nc
import xarray as xr
from tqdm import tqdm
import concurrent.futures
import traceback

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger()

# 错误代码常量
ERROR_CODES = {
    "NO_DATA": 1001,
    "INVALID_FILE": 1002,
    "DOWNLOAD_FAILED": 1003,
    "GEE_ERROR": 2001
}

# 数据集配置
DATASET_CONFIG = {
    "ERA5": {
        "collection_id": "ECMWF/ERA5_LAND/HOURLY",
        "bands": [
            'dewpoint_temperature_2m', 'temperature_2m', 'surface_pressure',
            'total_precipitation', 'u_component_of_wind_10m', 'v_component_of_wind_10m'
        ],
        "subfolder": "ERA5",
        "filename_prefix": "ERA5",
        "variables": [
            'dewpoint_temperature_2m', 'temperature_2m', 'surface_pressure',
            'total_precipitation', 'u_component_of_wind_10m', 'v_component_of_wind_10m'
        ]
    },
    "MERRA2_slv": {
        "collection_id": "NASA/GSFC/MERRA/slv/2",
        "bands": ['TO3', 'TQV'],
        "subfolder": "MERRA2_slv",
        "filename_prefix": "MERRA2",
        "variables": ['TO3', 'TQV']
    },
    "MERRA2_aer": {
        "collection_id": "NASA/GSFC/MERRA/aer/2",
        "bands": ['TOTEXTTAU'],
        "subfolder": "MERRA2_aer",
        "filename_prefix": "MERRA2",
        "variables": ['AOT550']
    }
}


def GEE_authorizing(credentials_path):
    """初始化Google Earth Engine认证"""
    service_account = "lobstyu@premium-cipher-424203-d0.iam.gserviceaccount.com"
    try:
        credentials = ee.ServiceAccountCredentials(service_account, credentials_path)
        ee.Initialize(credentials)
        logger.info("GEE 初始化成功")
    except Exception as e:
        logger.error(f"GEE 初始化失败: {e}")
        raise


def read_luts_stations(luts_path):
    """从LUTs.nc文件中读取站点信息"""
    try:
        ds = xr.open_dataset(luts_path)
        logger.info(f"成功读取 LUTs.nc 文件")

        stations = ds['Station'].values
        lats = ds['Lat'].values
        lons = ds['Lon'].values

        return stations, lats, lons
    except Exception as e:
        logger.error(f"读取 LUTs.nc 文件失败: {e}")
        raise


def get_feature_collection(stations, lats, lons):
    """创建GEE FeatureCollection"""
    try:
        features = []
        for station, lat, lon in zip(stations, lats, lons):
            feature = ee.Feature(
                ee.Geometry.Point(lon, lat),
                {'Station': station}
            )
            features.append(feature)

        fc = ee.FeatureCollection(features)
        logger.info("成功创建 FeatureCollection")
        return fc
    except Exception as e:
        logger.error(f"创建 FeatureCollection 失败: {e}")
        raise


def is_valid_netcdf(file_path, expected_stations, dataset_type):
    """检查NetCDF文件是否有效"""
    try:
        with nc.Dataset(file_path, 'r') as ds:
            # 检查维度
            if 'Station' not in ds.dimensions:
                return False

            # 检查站点数量
            if len(ds.dimensions['Station']) != len(expected_stations):
                return False

            # 检查关键变量
            config = DATASET_CONFIG[dataset_type]
            for var in config["variables"]:
                if var not in ds.variables:
                    return False

            # 检查数据填充情况
            for var in config["variables"]:
                data = ds.variables[var][:]
                if np.all(data == -9999.0) or np.any(np.isnan(data)):
                    return False

            # 检查文件大小
            if os.path.getsize(file_path) < 1024:  # 1KB作为最小文件大小
                return False

            return True
    except Exception:
        return False


def save_hourly_data(dt, data_dict, stations, lats, lons, base_path, dataset_type):
    """保存单小时数据到单独的NC文件"""
    config = DATASET_CONFIG[dataset_type]
    subfolder = config["subfolder"]

    try:
        # 转换时间为Python datetime对象
        if isinstance(dt, np.datetime64):
            dt = pd.Timestamp(dt).to_pydatetime()

        # 创建年月目录
        year = dt.strftime("%Y")
        month = dt.strftime("%m")
        dir_path = os.path.join(base_path, subfolder, year, month)
        os.makedirs(dir_path, exist_ok=True)

        # 文件路径
        time_str = dt.strftime('%Y%m%d_%H%M')
        filename = f"{config['filename_prefix']}_{time_str}"

        # 添加特定后缀
        if dataset_type == "MERRA2_aer":
            filename += "_AOT550.nc"
        elif dataset_type == "MERRA2_slv":
            filename += "_TO3_TQV.nc"
        else:
            filename += ".nc"

        file_path = os.path.join(dir_path, filename)

        # 如果文件已存在且有效，则跳过
        if os.path.exists(file_path) and is_valid_netcdf(file_path, stations, dataset_type):
            logger.info(f"文件已存在且有效，跳过: {file_path}")
            return True

        # 创建新的NC文件
        with nc.Dataset(file_path, 'w', format='NETCDF4') as ds:
            # 定义维度
            ds.createDimension('Station', len(stations))

            # 计算最大字符串长度
            max_str_len = max(len(str(s)) for s in stations) + 1

            # 定义变量
            station_var = ds.createVariable('Station', f'S{max_str_len}', ('Station',))
            lat_var = ds.createVariable('Lat', 'f4', ('Station',))
            lon_var = ds.createVariable('Lon', 'f4', ('Station',))

            # 设置全局时间属性
            ds.setncattr('time', dt.strftime('%Y-%m-%d %H:%M:%S'))
            ds.setncattr('datetime', dt.isoformat())

            # 写入站点数据
            station_arr = np.array([np.bytes_(str(s)) for s in stations], dtype=f'S{max_str_len}')
            station_var[:] = station_arr
            lat_var[:] = lats
            lon_var[:] = lons

            # 写入气象数据
            for var_name in config["variables"]:
                # 处理MERRA2_aer的特殊情况
                if dataset_type == "MERRA2_aer" and var_name == "AOT550":
                    data = data_dict.get("TOTEXTTAU", [-9999.0] * len(stations))
                else:
                    data = data_dict.get(var_name, [-9999.0] * len(stations))

                var = ds.createVariable(var_name, 'f4', ('Station',), fill_value=-9999.0)

                # 设置变量属性
                if var_name == "TO3":
                    var.long_name = 'Total Ozone Column'
                    var.units = 'Dobson Units'
                elif var_name == "TQV":
                    var.long_name = 'Total Precipitable Water Vapor'
                    var.units = 'kg/m^2'
                elif var_name == "AOT550":
                    var.long_name = 'Total Aerosol Optical Depth at 550 nm'
                    var.units = '1'

                var[:] = data

        # 保存后立即验证文件
        if not is_valid_netcdf(file_path, stations, dataset_type):
            logger.warning(f"保存的文件无效，删除: {file_path}")
            os.remove(file_path)
            return False

        return True
    except Exception as e:
        # 如果保存过程中出错，删除可能存在的无效文件
        if 'file_path' in locals() and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        logger.error(f"保存 {dt} 数据失败: {e}")
        traceback.print_exc()
        return False


def process_hourly_data(dt, collection, poi_fc, stations, lats, lons, base_path, dataset_type, max_retries=5):
    """处理单小时数据并保存到单独文件（带重试机制）"""
    config = DATASET_CONFIG[dataset_type]
    bands = config["bands"]

    retry_count = 0
    last_error = None

    while retry_count < max_retries:
        try:
            # 转换时间为Python datetime对象
            if isinstance(dt, np.datetime64):
                dt = pd.Timestamp(dt).to_pydatetime()

            # 计算时间范围（整点）
            start_dt = dt.strftime('%Y-%m-%dT%H:%M:%S')
            end_dt = (dt + datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S')

            # 获取该小时数据
            image = collection.filterDate(start_dt, end_dt).first()

            if image is None:
                logger.warning(f"{start_dt} 没有数据")
                last_error = (ERROR_CODES["NO_DATA"], f"{start_dt} 没有数据")
                raise ValueError(f"{start_dt} 没有数据")

            # 选择所需波段
            image = image.select(bands)

            # 采样POI
            sampled = image.sampleRegions(
                collection=poi_fc,
                scale=1000,
                geometries=False
            )

            # 获取采样结果
            sampled_dict = sampled.getInfo()

            # 检查采样结果
            if 'features' not in sampled_dict or len(sampled_dict['features']) == 0:
                logger.warning(f"{start_dt} 没有采样结果")
                last_error = (ERROR_CODES["NO_DATA"], f"{start_dt} 没有采样结果")
                raise ValueError(f"{start_dt} 没有采样结果")

            # 提取数据
            data_dict = {band: [] for band in bands}
            station_ids = []

            for feature in sampled_dict['features']:
                props = feature['properties']
                station_ids.append(props['Station'])
                for band in bands:
                    value = props.get(band)
                    if value is None:
                        value = -9999.0
                    data_dict[band].append(value)

            # 按原始站点顺序排序
            sorted_data = {band: [] for band in bands}
            for station in stations:
                if station in station_ids:
                    idx = station_ids.index(station)
                    for band in bands:
                        sorted_data[band].append(data_dict[band][idx])
                else:
                    for band in bands:
                        sorted_data[band].append(-9999.0)

            # 保存数据
            success = save_hourly_data(dt, sorted_data, stations, lats, lons, base_path, dataset_type)
            if success:
                return True
            else:
                last_error = (ERROR_CODES["INVALID_FILE"], f"保存的文件无效: {dt}")
                raise RuntimeError(f"保存的文件无效: {dt}")

        except Exception as e:
            retry_count += 1
            error_type = type(e).__name__
            logger.warning(f"处理 {dt} 时出错 ({error_type}): {e}，重试 {retry_count}/{max_retries}")

            # 指数退避等待 (5, 10, 20, 40, 80秒)
            sleep_time = 5 * (2 ** (retry_count - 1))
            time.sleep(sleep_time)

    # 达到最大重试次数后处理
    logger.error(f"处理 {dt} 失败，已达到最大重试次数")
    if last_error:
        logger.error(f"最后错误: {last_error[1]}")
    traceback.print_exc()
    return False


def generate_hourly_times(start_date, end_date):
    """生成指定日期范围内的所有整点时间"""
    hourly_times = []

    # 确保日期是datetime.date对象
    if isinstance(start_date, str):
        start_date = datetime.datetime.strptime(start_date, "%Y%m%d").date()
    if isinstance(end_date, str):
        end_date = datetime.datetime.strptime(end_date, "%Y%m%d").date()

    # 将开始日期转换为datetime对象（包含时间）
    current_dt = datetime.datetime.combine(start_date, datetime.time(0, 0))
    end_dt = datetime.datetime.combine(end_date, datetime.time(23, 0))

    # 生成所有整点时间
    while current_dt <= end_dt:
        hourly_times.append(current_dt)
        current_dt += datetime.timedelta(hours=1)

    return hourly_times


def download_dataset(dataset_type, start_date, end_date, base_path, credentials_path, max_workers=4):
    """下载指定数据集的数据"""
    # 初始化GEE
    GEE_authorizing(credentials_path)

    # 读取站点信息
    luts_path = os.path.join(base_path, "LUTs.nc")
    stations, lats, lons = read_luts_stations(luts_path)
    logger.info(f"共读取 {len(stations)} 个站点")

    # 创建FeatureCollection
    poi_fc = get_feature_collection(stations, lats, lons)

    # 生成时间列表
    hourly_times = generate_hourly_times(start_date, end_date)
    logger.info(f"生成时间范围: {start_date} 到 {end_date}, 共 {len(hourly_times)} 个整点时间")

    # 获取数据集配置
    config = DATASET_CONFIG[dataset_type]

    # 加载数据集
    collection = ee.ImageCollection(config["collection_id"])
    logger.info(f"{dataset_type} 数据集加载成功")

    # 准备任务队列
    tasks = []
    for dt in hourly_times:
        if isinstance(dt, np.datetime64):
            py_dt = pd.Timestamp(dt).to_pydatetime()
        else:
            py_dt = dt

        year = py_dt.strftime("%Y")
        month = py_dt.strftime("%m")

        # 生成文件名
        time_str = py_dt.strftime('%Y%m%d_%H%M')
        filename = f"{config['filename_prefix']}_{time_str}"

        # 添加特定后缀
        if dataset_type == "MERRA2_aer":
            filename += "_AOT550.nc"
        elif dataset_type == "MERRA2_slv":
            filename += "_TO3_TQV.nc"
        else:
            filename += ".nc"

        # 文件路径
        file_path = os.path.join(base_path, config["subfolder"], year, month, filename)

        # 检查文件是否需要下载
        if not os.path.exists(file_path) or not is_valid_netcdf(file_path, stations, dataset_type):
            tasks.append(dt)
            # 删除无效文件
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"删除无效文件: {file_path}")
                except Exception as e:
                    logger.error(f"删除文件失败: {file_path}, {e}")

    logger.info(
        f"总时间点: {len(hourly_times)}, 已存在有效文件: {len(hourly_times) - len(tasks)}, 待处理: {len(tasks)}")

    # 使用线程池并行处理
    success_count = 0
    failed_count = 0
    total_tasks = len(tasks)

    with tqdm(total=total_tasks, desc=f"下载{dataset_type}数据") as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(
                process_hourly_data,
                dt, collection, poi_fc, stations, lats, lons, base_path, dataset_type
            ): dt for dt in tasks}

            for future in concurrent.futures.as_completed(futures):
                dt = futures[future]
                try:
                    if future.result():
                        success_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.error(f"任务处理异常: {e}")
                    failed_count += 1

                pbar.update(1)
                pbar.set_postfix_str(f"成功: {success_count}, 失败: {failed_count}")

    logger.info(f"处理完成! 成功: {success_count}, 失败: {failed_count}, 总数: {total_tasks}")


def select_data_type():
    """让用户选择数据类型"""
    print("\n请选择要下载的数据类型:")
    print("1. ERA5 (Meterological factors)")
    print("2. MERRA2_slv (TO3, TQV)")
    print("3. MERRA2_aer (AOT_550nm)")

    while True:
        try:
            choice = int(input("请输入选项编号 (1-3): "))
            if choice == 1:
                return "ERA5"
            elif choice == 2:
                return "MERRA2_slv"
            elif choice == 3:
                return "MERRA2_aer"
            print("输入无效，请重新输入")
        except ValueError:
            print("请输入有效数字")


def get_date_range():
    """获取用户输入的日期范围 (YYYYMMDD-YYYYMMDD格式)"""
    default_start = "20150607"
    default_end = "20250131"

    print(f"\n请输入日期范围 (格式: YYYYMMDD-YYYYMMDD, 默认: {default_start}-{default_end})")
    date_input = input("日期范围: ").strip()

    if not date_input:
        return default_start, default_end

    if "-" in date_input:
        start_str, end_str = date_input.split("-")
        return start_str.strip(), end_str.strip()

    print(f"格式错误，使用默认日期范围: {default_start}-{default_end}")
    return default_start, default_end


def get_thread_count():
    """获取线程数 (1-8)"""
    default = 6
    print(f"\n请输入线程数 (1-8, 默认: {default})")
    try:
        count = int(input("线程数: ").strip())
        if 1 <= count <= 8:
            return count
        print(f"超出范围，使用默认值 {default}")
    except ValueError:
        print(f"输入无效，使用默认值 {default}")
    return default


def get_data_path():
    """获取数据存储路径"""
    default = r"D:\H8_data"
    print(f"\n请输入数据存储路径 (默认: {default})")
    path = input("路径: ").strip()
    return path or default


def get_credentials_path():
    """获取GEE凭证文件路径"""
    default = "premium-cipher-424203-d0-c6894a29d00c.json"
    print(f"\n请输入GEE凭证文件路径 (默认: {default})")
    path = input("路径: ").strip()
    return path or default


def main():
    """主函数 - 交互式终端界面"""
    print("=" * 50)
    print("气象数据集下载工具")
    print("=" * 50)

    # 1. 选择数据类型
    dataset_type = select_data_type()

    # 2. 输入日期范围
    print("\n" + "=" * 50)
    print("日期范围设置")
    print("=" * 50)
    start_date, end_date = get_date_range()

    # 3. 输入线程数
    print("\n" + "=" * 50)
    print("并行设置")
    print("=" * 50)
    max_workers = get_thread_count()

    # 4. 输入主文件夹路径
    print("\n" + "=" * 50)
    print("数据存储设置")
    print("=" * 50)
    base_path = get_data_path()

    # 5. 输入凭证文件路径
    print("\n" + "=" * 50)
    print("GEE认证设置")
    print("=" * 50)
    credentials_path = get_credentials_path()

    # 检查LUTs.nc文件是否存在
    luts_path = os.path.join(base_path, "LUTs.nc")
    if not os.path.exists(luts_path):
        print(f"\n错误: LUTs.nc 文件在 '{base_path}' 中不存在!")
        print("请确保LUTs.nc文件位于主文件夹中")
        return

    # 确认信息
    print("\n" + "=" * 50)
    print("下载配置确认")
    print("=" * 50)
    print(f"数据类型: {dataset_type}")
    print(f"日期范围: {start_date}-{end_date}")
    print(f"线程数: {max_workers}")
    print(f"主文件夹路径: {base_path}")
    print(f"凭证文件路径: {credentials_path}")
    print(f"LUTs.nc 位置: {luts_path}")

    confirm = input("\n是否开始下载? (y/n): ").strip().lower()
    if confirm != 'y':
        print("下载已取消")
        return

    # 开始下载
    try:
        print("\n" + "=" * 50)
        print("开始下载数据")
        print("=" * 50)
        download_dataset(
            dataset_type=dataset_type,
            start_date=start_date,
            end_date=end_date,
            base_path=base_path,
            credentials_path=credentials_path,
            max_workers=max_workers
        )
    except Exception as e:
        logger.error(f"下载过程中出错: {e}")
        traceback.print_exc()
    finally:
        print("\n" + "=" * 50)
        print("程序执行完成")
        print("=" * 50)


if __name__ == "__main__":
    main()