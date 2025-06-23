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
from threading import Lock
import traceback

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

# 全局锁，用于保护NetCDF文件写入
nc_lock = Lock()


def GEE_authorizing():
    service_account = "lobstyu@premium-cipher-424203-d0.iam.gserviceaccount.com"
    credentials_path = 'premium-cipher-424203-d0-c6894a29d00c.json'
    try:
        credentials = ee.ServiceAccountCredentials(service_account, credentials_path)
        ee.Initialize(credentials)
        logging.info("GEE 初始化成功")
    except Exception as e:
        logging.error(f"GEE 初始化失败: {e}")
        raise


def read_luts_nc(luts_path):
    """从LUTs.nc文件中读取站点和时间信息"""
    try:
        ds = xr.open_dataset(luts_path)
        logging.info(f"成功读取 LUTs.nc 文件")

        # 获取站点和时间信息
        stations = ds['Station'].values
        lats = ds['Lat'].values
        lons = ds['Lon'].values
        times = ds['time'].values

        # 筛选整点时间（小时）
        hourly_times = []
        for t in times:
            dt = pd.to_datetime(t)
            if dt.minute == 0 and dt.second == 0:
                hourly_times.append(dt)

        return stations, lats, lons, hourly_times

    except Exception as e:
        logging.error(f"读取 LUTs.nc 文件失败: {e}")
        raise


def create_or_open_era5_nc(output_path, stations, lats, lons, times):
    """创建或打开ERA5.nc文件"""
    try:
        if os.path.exists(output_path):
            # 文件存在，以追加模式打开
            ds = nc.Dataset(output_path, 'a', format='NETCDF4')
            logging.info(f"打开已存在的 ERA5.nc 文件: {output_path}")

            # 检查时间变量是否已创建
            if 'time' not in ds.variables:
                # 如果时间变量不存在，创建它
                time_var = ds.createVariable('time', 'f8', ('time',))
                time_var.units = 'hours since 2015-07-07 00:00:00'
                time_var.calendar = 'standard'
                time_var[:] = np.full(len(times), -9999.0)

            # 检查气象变量是否已创建
            band_names = [
                'dewpoint_temperature_2m',
                'temperature_2m',
                'surface_pressure',
                'total_precipitation',
                'u_component_of_wind_10m',
                'v_component_of_wind_10m'
            ]

            vars_dict = {}
            for band in band_names:
                if band in ds.variables:
                    vars_dict[band] = ds.variables[band]
                else:
                    var = ds.createVariable(
                        band, 'f4', ('time', 'Station'),
                        fill_value=-9999.0,
                        zlib=True
                    )
                    # 初始化数据
                    var[:] = np.full((len(times), len(stations)), -9999.0)
                    vars_dict[band] = var

            return ds, vars_dict
        else:
            # 文件不存在，创建新文件
            ds = nc.Dataset(output_path, 'w', format='NETCDF4')

            # 定义维度
            ds.createDimension('time', len(times))
            ds.createDimension('Station', len(stations))

            # 定义坐标变量
            time_var = ds.createVariable('time', 'f8', ('time',))
            station_var = ds.createVariable('Station', str, ('Station',))
            lat_var = ds.createVariable('Lat', 'f4', ('Station',))
            lon_var = ds.createVariable('Lon', 'f4', ('Station',))

            # 设置坐标变量属性
            time_var.units = 'hours since 2015-07-07 00:00:00'
            time_var.calendar = 'standard'

            # 初始化时间变量为缺省值
            time_var[:] = np.full(len(times), -9999.0)

            # 写入坐标数据
            station_var[:] = stations
            lat_var[:] = lats
            lon_var[:] = lons

            # 定义气象变量
            band_names = [
                'dewpoint_temperature_2m',
                'temperature_2m',
                'surface_pressure',
                'total_precipitation',
                'u_component_of_wind_10m',
                'v_component_of_wind_10m'
            ]

            vars_dict = {}
            for band in band_names:
                var = ds.createVariable(
                    band, 'f4', ('time', 'Station'),
                    fill_value=-9999.0,
                    zlib=True
                )
                # 初始化数据
                var[:] = np.full((len(times), len(stations)), -9999.0)
                vars_dict[band] = var

            ds.sync()
            logging.info(f"创建新的 ERA5.nc 文件成功: {output_path}")
            return ds, vars_dict

    except Exception as e:
        logging.error(f"处理 ERA5.nc 文件失败: {e}")
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


def process_hourly_data(dt, collection, bands, poi_fc, ds_out, vars_dict, time_index, max_retries=5):
    """处理单小时数据并写入NetCDF（带重试机制）"""
    retry_count = 0
    while retry_count < max_retries:
        try:
            # 计算时间范围（整点）
            start_dt = dt.strftime('%Y-%m-%dT%H:%M:%S')
            end_dt = (dt + datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S')

            # 获取该小时数据
            image = collection.filterDate(start_dt, end_dt).first()

            if image is None:
                logging.warning(f"{start_dt} 没有数据")
                return False

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
                return False

            # 提取数据
            data_dict = {band: [] for band in bands}
            station_ids = []

            for feature in sampled_dict['features']:
                props = feature['properties']
                station_ids.append(props['Station'])
                for band in bands:
                    data_dict[band].append(props.get(band, np.nan))

            # 按原始站点顺序排序
            sorted_data = {band: [] for band in bands}
            for station in ds_out['Station'][:]:
                if station in station_ids:
                    idx = station_ids.index(station)
                    for band in bands:
                        sorted_data[band].append(data_dict[band][idx])
                else:
                    for band in bands:
                        sorted_data[band].append(np.nan)

            # 使用锁保护写入操作
            with nc_lock:
                # 写入NetCDF
                for band in bands:
                    vars_dict[band][time_index, :] = sorted_data[band]

                # 写入时间
                time_var = ds_out.variables['time']
                time_var[time_index] = nc.date2num(dt, time_var.units, time_var.calendar)

                # 定期同步数据到磁盘（每10次写入同步一次）
                if time_index % 10 == 0:
                    ds_out.sync()

            return True

        except Exception as e:
            retry_count += 1
            error_type = type(e).__name__
            logging.warning(f"处理 {dt} 时出错 ({error_type}): {e}，重试 {retry_count}/{max_retries}")
            time.sleep(5 * retry_count)  # 指数退避等待

            if retry_count >= max_retries:
                logging.error(f"处理 {dt} 失败，已达到最大重试次数")
                traceback.print_exc()
                return False


def main():
    # 初始化 GEE
    GEE_authorizing()

    # 数据路径
    data_path = "D:/H8_data"
    luts_path = os.path.join(data_path, "LUTs.nc")
    era5_path = os.path.join(data_path, "ERA5.nc")

    # 读取LUTs.nc文件
    stations, lats, lons, hourly_times = read_luts_nc(luts_path)
    logging.info(f"共读取 {len(stations)} 个站点，{len(hourly_times)} 个整点时间")

    # 创建或打开ERA5.nc文件
    ds_out, vars_dict = create_or_open_era5_nc(era5_path, stations, lats, lons, hourly_times)

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

    # 确定需要处理的时间点
    time_var = ds_out.variables['time']
    processed_indices = set()
    time_values = time_var[:]

    # 找到已处理的时间点
    for i, t in enumerate(time_values):
        if t != -9999.0:  # 使用初始化时的缺省值判断
            processed_indices.add(i)

    # 准备任务队列
    tasks = []
    for time_index, dt in enumerate(hourly_times):
        if time_index not in processed_indices:
            tasks.append((time_index, dt))

    logging.info(f"总时间点: {len(hourly_times)}, 已处理: {len(processed_indices)}, 待处理: {len(tasks)}")

    # 使用线程池并行处理
    success_count = 0
    failed_count = 0
    total_tasks = len(tasks)

    # 设置并行线程数（GEE限制为10）
    max_workers = 8

    with tqdm(total=total_tasks, desc="下载进度") as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            futures = {executor.submit(
                process_hourly_data,
                dt, collection, bands, poi_fc, ds_out, vars_dict, time_index
            ): (time_index, dt) for time_index, dt in tasks}

            # 处理完成的任务
            for future in concurrent.futures.as_completed(futures):
                time_index, dt = futures[future]
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

    # 最终同步并关闭文件
    ds_out.sync()
    ds_out.close()
    logging.info(f"处理完成! 成功: {success_count}, 失败: {failed_count}, 总数: {total_tasks}")


if __name__ == "__main__":
    main()