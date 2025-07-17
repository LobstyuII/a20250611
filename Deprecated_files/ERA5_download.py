import ee
import pandas as pd
import datetime
import os
import math
import logging
import time
import numpy as np
import netCDF4 as nc
import xarray as xr
from tqdm import tqdm
import concurrent.futures
import traceback
import shutil

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)

# 添加错误代码常量
ERROR_CODES = {
    "NO_DATA": 1001,
    "INVALID_FILE": 1002,
    "DOWNLOAD_FAILED": 1003,
    "GEE_ERROR": 2001
}


def GEE_authorizing():
    service_account = "lobstyu@premium-cipher-424203-d0.iam.gserviceaccount.com"
    credentials_path = '../premium-cipher-424203-d0-c6894a29d00c.json'
    try:
        credentials = ee.ServiceAccountCredentials(service_account, credentials_path)
        ee.Initialize(credentials)
        logging.info("GEE 初始化成功")
    except Exception as e:
        logging.error(f"GEE 初始化失败: {e}")
        raise


def read_luts_stations(luts_path):
    """从LUTs.nc文件中读取站点信息（不包括时间）"""
    try:
        ds = xr.open_dataset(luts_path)
        logging.info(f"成功读取 LUTs.nc 文件")

        stations = ds['Station'].values
        lats = ds['Lat'].values
        lons = ds['Lon'].values

        return stations, lats, lons

    except Exception as e:
        logging.error(f"读取 LUTs.nc 文件失败: {e}")
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
        logging.info("成功创建 FeatureCollection")
        return fc

    except Exception as e:
        logging.error(f"创建 FeatureCollection 失败: {e}")
        raise


def is_valid_netcdf(file_path, expected_stations):
    """检查NetCDF文件是否有效"""
    try:
        with nc.Dataset(file_path, 'r') as ds:
            # 检查维度
            if 'Station' not in ds.dimensions or 'time' not in ds.dimensions:
                return False

            # 检查站点数量
            if len(ds.dimensions['Station']) != len(expected_stations):
                return False

            # 检查关键变量
            required_vars = [
                'dewpoint_temperature_2m',
                'temperature_2m',
                'surface_pressure',
                'total_precipitation',
                'u_component_of_wind_10m',
                'v_component_of_wind_10m'
            ]

            for var in required_vars:
                if var not in ds.variables:
                    return False

            # 检查数据填充情况
            for var in required_vars:
                data = ds.variables[var][:]
                if np.all(data == -9999.0) or np.any(np.isnan(data)):
                    return False

        # 检查文件大小
        if os.path.getsize(file_path) < 1024:  # 1KB作为最小文件大小
            return False

        return True
    except Exception:
        return False


def save_hourly_data(dt, data_dict, stations, lats, lons, base_path):
    """保存单小时数据到单独的NC文件"""
    try:
        # 转换 numpy.datetime64 为 Python datetime
        if isinstance(dt, np.datetime64):
            dt = pd.Timestamp(dt).to_pydatetime()

        # 创建年月目录
        year = dt.strftime("%Y")
        month = dt.strftime("%m")
        dir_path = os.path.join(base_path, "ERA5", year, month)
        os.makedirs(dir_path, exist_ok=True)

        # 文件路径
        filename = f"ERA5_{dt.strftime('%Y%m%d_%H%M')}.nc"
        file_path = os.path.join(dir_path, filename)

        # 如果文件已存在且有效，则跳过
        if os.path.exists(file_path) and is_valid_netcdf(file_path, stations):
            logging.info(f"文件已存在且有效，跳过: {file_path}")
            return True

        # 创建新的NC文件
        with nc.Dataset(file_path, 'w', format='NETCDF4') as ds:
            # 定义维度
            ds.createDimension('Station', len(stations))
            ds.createDimension('time', 1)

            # 定义变量
            time_var = ds.createVariable('time', 'f8', ('time',))
            station_var = ds.createVariable('Station', str, ('Station',))
            lat_var = ds.createVariable('Lat', 'f4', ('Station',))
            lon_var = ds.createVariable('Lon', 'f4', ('Station',))

            # 设置时间属性
            time_var.units = 'hours since 2015-06-07 00:00:00'
            time_var.calendar = 'standard'

            # 写入坐标数据
            time_var[:] = nc.date2num(dt, time_var.units, time_var.calendar)
            station_var[:] = np.array(stations, dtype=object)
            lat_var[:] = lats
            lon_var[:] = lons

            # 写入气象数据
            band_names = [
                'dewpoint_temperature_2m',
                'temperature_2m',
                'surface_pressure',
                'total_precipitation',
                'u_component_of_wind_10m',
                'v_component_of_wind_10m'
            ]

            for band in band_names:
                var = ds.createVariable(band, 'f4', ('time', 'Station'), fill_value=-9999.0)
                var[0, :] = data_dict[band]

        # 保存后立即验证文件
        if not is_valid_netcdf(file_path, stations):
            logging.warning(f"保存的文件无效，删除: {file_path}")
            os.remove(file_path)
            return False

        return True
    except Exception as e:
        # 如果保存过程中出错，删除可能存在的无效文件
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        logging.error(f"保存 {dt} 数据失败: {e}")
        traceback.print_exc()
        return False


def process_hourly_data(dt, collection, bands, poi_fc, stations, lats, lons, base_path, max_retries=5):
    """处理单小时数据并保存到单独文件（带重试机制）"""
    retry_count = 0
    last_error = None

    while retry_count < max_retries:
        try:
            # 转换 numpy.datetime64 为 Python datetime
            if isinstance(dt, np.datetime64):
                dt = pd.Timestamp(dt).to_pydatetime()

            # 计算时间范围（整点）
            start_dt = dt.strftime('%Y-%m-%dT%H:%M:%S')
            end_dt = (dt + datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S')

            # 获取该小时数据
            image = collection.filterDate(start_dt, end_dt).first()

            if image is None:
                logging.warning(f"{start_dt} 没有数据")
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
                logging.warning(f"{start_dt} 没有采样结果")
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

            # 保存到单独文件
            success = save_hourly_data(dt, sorted_data, stations, lats, lons, base_path)
            if success:
                return True
            else:
                last_error = (ERROR_CODES["INVALID_FILE"], f"保存的文件无效: {dt}")
                raise RuntimeError(f"保存的文件无效: {dt}")

        except Exception as e:
            retry_count += 1
            error_type = type(e).__name__
            logging.warning(f"处理 {dt} 时出错 ({error_type}): {e}，重试 {retry_count}/{max_retries}")

            # 指数退避等待 (5, 10, 20, 40, 80秒)
            sleep_time = 5 * (2 ** (retry_count - 1))
            time.sleep(sleep_time)

    # 达到最大重试次数后处理
    logging.error(f"处理 {dt} 失败，已达到最大重试次数")
    if last_error:
        logging.error(f"最后错误: {last_error[1]}")
    traceback.print_exc()
    return False


def generate_hourly_times(start_date, end_date):
    """生成指定日期范围内的所有整点时间"""
    hourly_times = []

    if isinstance(start_date, str):
        start_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
    if isinstance(end_date, str):
        end_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()

    current_dt = datetime.datetime.combine(start_date, datetime.time(0, 0))
    end_dt = datetime.datetime.combine(end_date, datetime.time(23, 0))

    while current_dt <= end_dt:
        hourly_times.append(current_dt)
        current_dt += datetime.timedelta(hours=1)

    return hourly_times


def main():
    # 初始化 GEE
    GEE_authorizing()

    # 数据路径
    data_path = "D:/H8_data"
    luts_path = os.path.join(data_path, "LUTs.nc")

    # 1. 读取LUTs.nc文件获取站点信息
    stations, lats, lons = read_luts_stations(luts_path)
    logging.info(f"共读取 {len(stations)} 个站点")

    # 2. 明码指定时间范围
    start_date = datetime.date(2015, 6, 7)
    end_date = datetime.date(2024, 12, 31)

    # 3. 生成整点时间列表
    hourly_times = generate_hourly_times(start_date, end_date)
    logging.info(f"生成时间范围: {start_date} 到 {end_date}, 共 {len(hourly_times)} 个整点时间")

    # 创建FeatureCollection
    poi_fc = get_feature_collection(stations, lats, lons)

    # 定义GEE ImageCollection和波段
    collection = ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY")
    bands = [
        'dewpoint_temperature_2m',
        'temperature_2m',
        'surface_pressure',
        'total_precipitation',
        'u_component_of_wind_10m',
        'v_component_of_wind_10m'
    ]
    logging.info("ERA5 数据集加载成功")

    # 准备任务队列
    tasks = []
    for dt in hourly_times:
        if isinstance(dt, np.datetime64):
            py_dt = pd.Timestamp(dt).to_pydatetime()
        else:
            py_dt = dt

        year = py_dt.strftime("%Y")
        month = py_dt.strftime("%m")
        filename = f"ERA5_{py_dt.strftime('%Y%m%d_%H%M')}.nc"
        file_path = os.path.join(data_path, "ERA5", year, month, filename)

        # 检查文件是否需要下载
        if not os.path.exists(file_path) or not is_valid_netcdf(file_path, stations):
            tasks.append(dt)
            # 删除无效文件
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logging.info(f"删除无效文件: {file_path}")
                except Exception as e:
                    logging.error(f"删除文件失败: {file_path}, {e}")

    logging.info(
        f"总时间点: {len(hourly_times)}, 已存在有效文件: {len(hourly_times) - len(tasks)}, 待处理: {len(tasks)}")

    # 使用线程池并行处理
    success_count = 0
    failed_count = 0
    total_tasks = len(tasks)

    # 设置并行线程数
    max_workers = 8

    with tqdm(total=total_tasks, desc="下载ERA5数据") as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(
                process_hourly_data,
                dt, collection, bands, poi_fc, stations, lats, lons, data_path
            ): dt for dt in tasks}

            for future in concurrent.futures.as_completed(futures):
                dt = futures[future]
                try:
                    result = future.result()
                    if result:
                        success_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    logging.error(f"任务处理异常: {e}")
                    failed_count += 1

                pbar.update(1)
                pbar.set_postfix_str(f"成功: {success_count}, 失败: {failed_count}")

    logging.info(f"处理完成! 成功: {success_count}, 失败: {failed_count}, 总数: {total_tasks}")


if __name__ == "__main__":
    main()
