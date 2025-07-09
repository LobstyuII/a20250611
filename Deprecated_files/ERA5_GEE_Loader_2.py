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


def read_luts_nc(luts_path):
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


def save_hourly_data(dt, data_dict, stations, lats, lons, base_path):
    try:
        if isinstance(dt, np.datetime64):
            dt = pd.Timestamp(dt).to_pydatetime()

        year = dt.strftime("%Y")
        month = dt.strftime("%m")
        dir_path = os.path.join(base_path, "ERA5", year, month)
        os.makedirs(dir_path, exist_ok=True)

        filename = f"ERA5_{dt.strftime('%Y%m%d_%H%M')}.nc"
        file_path = os.path.join(dir_path, filename)

        if os.path.exists(file_path) and os.path.getsize(file_path) > 1024:
            return True

        with nc.Dataset(file_path, 'w', format='NETCDF4') as ds:
            ds.createDimension('Station', len(stations))

            station_var = ds.createVariable('Station', str, ('Station',))
            lat_var = ds.createVariable('Lat', 'f4', ('Station',))
            lon_var = ds.createVariable('Lon', 'f4', ('Station',))

            station_var[:] = np.array(stations, dtype=object)
            lat_var[:] = lats
            lon_var[:] = lons

            band_names = [
                'dewpoint_temperature_2m',
                'temperature_2m',
                'surface_pressure',
                'total_precipitation',
                'u_component_of_wind_10m',
                'v_component_of_wind_10m'
            ]

            for band in band_names:
                var = ds.createVariable(band, 'f4', ('Station',), fill_value=-9999.0)
                var[:] = data_dict[band]

        return True
    except Exception as e:
        logging.error(f"保存 {dt} 数据失败: {e}")
        traceback.print_exc()
        return False


def process_hourly_data(dt, collection, bands, poi_fc, stations, lats, lons, base_path, max_retries=5):
    retry_count = 0
    while retry_count < max_retries:
        try:
            if isinstance(dt, np.datetime64):
                dt = pd.Timestamp(dt).to_pydatetime()

            start_dt = dt.strftime('%Y-%m-%dT%H:%M:%S')
            end_dt = (dt + datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S')

            image = collection.filterDate(start_dt, end_dt).first()

            if image is None:
                logging.warning(f"{start_dt} 没有数据")
                return False

            image = image.select(bands)

            sampled = image.sampleRegions(
                collection=poi_fc,
                scale=1000,
                geometries=False
            )

            sampled_dict = sampled.getInfo()

            if 'features' not in sampled_dict or len(sampled_dict['features']) == 0:
                logging.warning(f"{start_dt} 没有采样结果")
                return False

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

            sorted_data = {band: [] for band in bands}
            for station in stations:
                if station in station_ids:
                    idx = station_ids.index(station)
                    for band in bands:
                        sorted_data[band].append(data_dict[band][idx])
                else:
                    for band in bands:
                        sorted_data[band].append(-9999.0)

            return save_hourly_data(dt, sorted_data, stations, lats, lons, base_path)

        except Exception as e:
            retry_count += 1
            error_type = type(e).__name__
            logging.warning(f"处理 {dt} 时出错 ({error_type}): {e}，重试 {retry_count}/{max_retries}")
            time.sleep(5 * retry_count)

            if retry_count >= max_retries:
                logging.error(f"处理 {dt} 失败，已达到最大重试次数")
                traceback.print_exc()
                return False


def generate_hourly_times(start_date, end_date):
    """生成指定日期范围内的所有整点时间"""
    try:
        start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d") + datetime.timedelta(days=1)

        times = []
        current_dt = start_dt
        while current_dt < end_dt:
            times.append(current_dt)
            current_dt += datetime.timedelta(hours=1)

        return times
    except Exception as e:
        logging.error(f"生成时间范围失败: {e}")
        raise


def main():
    GEE_authorizing()

    data_path = "D:/H8_data"
    luts_path = os.path.join(data_path, "LUTs.nc")

    # 从LUTs.nc读取站点信息
    stations, lats, lons = read_luts_nc(luts_path)
    logging.info(f"共读取 {len(stations)} 个站点")

    # 用户自定义时间范围
    start_date = "2022-01-01"
    end_date = "2024-01-31"
    hourly_times = generate_hourly_times(start_date, end_date)
    logging.info(f"生成时间范围: {start_date} 到 {end_date}, 共 {len(hourly_times)} 个整点时间")

    poi_fc = get_feature_collection(stations, lats, lons)

    collection = ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY")
    bands = [
        'dewpoint_temperature_2m',
        'temperature_2m',
        'surface_pressure',
        'total_precipitation',
        'u_component_of_wind_10m',
        'v_component_of_wind_10m'
    ]

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

        if not os.path.exists(file_path) or os.path.getsize(file_path) <= 1024:
            tasks.append(dt)

    logging.info(f"总时间点: {len(hourly_times)}, 已存在: {len(hourly_times) - len(tasks)}, 待处理: {len(tasks)}")

    success_count = 0
    failed_count = 0
    total_tasks = len(tasks)

    max_workers = 8

    with tqdm(total=total_tasks, desc="下载进度") as pbar:
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


def merge_era5_data(base_path, output_path):
    try:
        all_files = []
        era5_dir = os.path.join(base_path, "ERA5")

        for root, dirs, files in os.walk(era5_dir):
            for file in files:
                if file.endswith(".nc") and file.startswith("ERA5_"):
                    all_files.append(os.path.join(root, file))

        if not all_files:
            logging.error("未找到ERA5数据文件")
            return

        logging.info(f"找到 {len(all_files)} 个数据文件，开始合并...")

        all_files.sort()

        ds_list = []
        for file in tqdm(all_files, desc="合并文件"):
            try:
                ds = xr.open_dataset(file)
                ds_list.append(ds)
            except Exception as e:
                logging.warning(f"无法打开文件 {file}: {e}")

        if not ds_list:
            logging.error("没有有效文件可合并")
            return

        combined = xr.concat(ds_list, dim="time")

        for ds in ds_list:
            ds.close()

        combined.to_netcdf(output_path)
        logging.info(f"成功合并数据到: {output_path}")

        try:
            ds = xr.open_dataset(output_path)
            logging.info(f"合并后数据集信息: {ds.dims}")
            ds.close()
        except Exception as e:
            logging.error(f"验证输出文件失败: {e}")

    except Exception as e:
        logging.error(f"合并数据失败: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()