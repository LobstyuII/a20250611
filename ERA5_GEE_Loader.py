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
    credentials_path = 'premium-cipher-424203-d0-c6894a29d00c.json'
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

        # 获取站点信息
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

        # 如果文件已存在且完整，则跳过
        if os.path.exists(file_path) and os.path.getsize(file_path) > 1024:  # 1KB作为最小文件大小
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
            time_var.units = 'hours since 2015-07-07 00:00:00'
            time_var.calendar = 'standard'

            # 写入坐标数据
            time_var[:] = nc.date2num(dt, time_var.units, time_var.calendar)
            station_var[:] = np.array(stations, dtype=object)  # 处理字符串数组
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

        return True
    except Exception as e:
        logging.error(f"保存 {dt} 数据失败: {e}")
        traceback.print_exc()
        return False


def process_hourly_data(dt, collection, bands, poi_fc, stations, lats, lons, base_path, max_retries=5):
    """处理单小时数据并保存到单独文件（带重试机制）"""
    retry_count = 0
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
                    # 处理可能的缺失值
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
            return save_hourly_data(dt, sorted_data, stations, lats, lons, base_path)

        except Exception as e:
            retry_count += 1
            error_type = type(e).__name__
            logging.warning(f"处理 {dt} 时出错 ({error_type}): {e}，重试 {retry_count}/{max_retries}")
            time.sleep(5 * retry_count)  # 指数退避等待

            if retry_count >= max_retries:
                logging.error(f"处理 {dt} 失败，已达到最大重试次数")
                traceback.print_exc()
                return False


def generate_hourly_times(start_date, end_date):
    """生成指定日期范围内的所有整点时间"""
    hourly_times = []

    # 确保日期是datetime.date对象
    if isinstance(start_date, str):
        start_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
    if isinstance(end_date, str):
        end_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()

    # 将开始日期转换为datetime对象（包含时间）
    current_dt = datetime.datetime.combine(start_date, datetime.time(0, 0))
    end_dt = datetime.datetime.combine(end_date, datetime.time(23, 0))

    # 生成所有整点时间
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
    start_date = datetime.date(2015, 7, 7)
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
        if not os.path.exists(file_path) or os.path.getsize(file_path) <= 1024:
            tasks.append(dt)

    logging.info(f"总时间点: {len(hourly_times)}, 已存在: {len(hourly_times) - len(tasks)}, 待处理: {len(tasks)}")

    # 使用线程池并行处理
    success_count = 0
    failed_count = 0
    total_tasks = len(tasks)

    # 设置并行线程数（GEE限制为10）
    max_workers = 8

    with tqdm(total=total_tasks, desc="下载ERA5数据") as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            futures = {executor.submit(
                process_hourly_data,
                dt, collection, bands, poi_fc, stations, lats, lons, data_path
            ): dt for dt in tasks}

            # 处理完成的任务
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
    """合并所有小时数据到单个NetCDF文件"""
    try:
        # 收集所有文件路径
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

        # 按文件名排序（即按时间排序）
        all_files.sort()

        # 使用xarray打开并合并文件
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

        # 沿时间维度合并
        combined = xr.concat(ds_list, dim="time")

        # 关闭所有文件
        for ds in ds_list:
            ds.close()

        # 保存合并后的数据集
        combined.to_netcdf(output_path)
        logging.info(f"成功合并数据到: {output_path}")

        # 验证文件
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
    # 第一步：下载数据
    main()

    # 第二步：合并数据（在下载完成后手动运行）
    # data_path = "D:/H8_data"
    # output_nc = os.path.join(data_path, "ERA5_combined.nc")
    # merge_era5_data(data_path, output_nc)