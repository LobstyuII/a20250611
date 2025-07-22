import os
import glob
import numpy as np
import xarray as xr
import pandas as pd
from datetime import datetime, timedelta
import netCDF4 as nc
from pathlib import Path
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp
import shutil

# 配置日志
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# 配置路径和参数
HOURLY_DIR = r'D:\H8_data\Hourly_TOA_Angles'
OUTPUT_DIR = r'D:\H8_data\NDVI_TimeSeries'
TEMP_DIR = r'D:\H8_data\NDVI_Temp'  # 临时处理目录
MAX_WORKERS = max(1, mp.cpu_count() - 2)  # 使用大部分CPU核心
DAILY_BATCH_SIZE = 30  # 每天处理的天数批次大小

# 设置日期范围
start_date = datetime(2015, 7, 7)
end_date = datetime(2018, 12, 31)


def get_all_stations():
    """获取所有站点名称"""
    sample_pattern = os.path.join(HOURLY_DIR, '2015', '07', 'H8_hourly_TOA_angles_20150707_*.nc')
    sample_files = glob.glob(sample_pattern)

    if not sample_files:
        raise FileNotFoundError("找不到示例文件来获取站点列表")

    sample_file = sample_files[0]
    with nc.Dataset(sample_file) as ds:
        stations = ds.variables['Station'][:]
    return stations


def get_time_index():
    """生成完整的时间索引"""
    time_index = []
    current_date = start_date
    while current_date <= end_date:
        for hour in list(range(0, 12)) + list(range(21, 24)):
            time_index.append(datetime(current_date.year, current_date.month,
                                       current_date.day, hour))
        current_date += timedelta(days=1)
    return pd.DatetimeIndex(time_index)


def get_daily_file_paths():
    """获取所有需要的每日文件路径（按天分组）"""
    daily_files = {}
    current_date = start_date
    while current_date <= end_date:
        year = current_date.year
        month = f"{current_date.month:02d}"
        day = f"{current_date.day:02d}"

        daily_files[current_date] = []
        for hour in list(range(0, 12)) + list(range(21, 24)):
            file_pattern = os.path.join(
                HOURLY_DIR, f"{year}", month,
                f"H8_hourly_TOA_angles_{year}{month}{day}_{hour:02d}00.nc"
            )
            matching_files = glob.glob(file_pattern)
            if matching_files:
                daily_files[current_date].append(matching_files[0])

        current_date += timedelta(days=1)
    return daily_files


def process_day_batch(day_batch, stations, time_index):
    """处理一批天的数据"""
    # 创建临时存储
    num_stations = len(stations)
    num_times = len(time_index)

    # 初始化所有站点的NDVI和状态数组
    all_ndvi = np.full((num_stations, num_times), np.nan, dtype=np.float32)
    all_status = np.full((num_stations, num_times), -1, dtype=np.int8)

    # 创建时间索引映射
    time_idx_map = {ts: idx for idx, ts in enumerate(time_index)}

    # 处理每一天
    for day, file_paths in day_batch.items():
        logger.info(f"处理日期: {day.strftime('%Y-%m-%d')}")

        # 处理该天的每个小时文件
        for file_path in file_paths:
            # 从文件路径解析时间
            filename = os.path.basename(file_path)
            hour = int(filename.split('_')[-1][:2])
            timestamp = datetime(day.year, day.month, day.day, hour)
            time_idx = time_idx_map[timestamp]

            try:
                with nc.Dataset(file_path) as ds:
                    # 一次性读取所有站点数据
                    availability = ds.variables['hourly_availability'][:]
                    albedo_03 = ds.variables['Albedo_03'][:]
                    albedo_04 = ds.variables['Albedo_04'][:]

                    # 计算NDVI
                    denominator = albedo_04 + albedo_03
                    valid_mask = (availability == 0) & (denominator > 0)

                    # 计算NDVI
                    ndvi = np.where(
                        valid_mask,
                        (albedo_04 - albedo_03) / denominator,
                        np.nan
                    )

                    # 应用物理限制
                    ndvi = np.clip(ndvi, -1, 1)

                    # 设置状态
                    status = np.where(
                        availability == 0,
                        np.where(valid_mask, 0, 1),
                        -1
                    )

                    # 更新到主数组
                    all_ndvi[:, time_idx] = ndvi
                    all_status[:, time_idx] = status

            except Exception as e:
                logger.error(f"处理文件 {file_path} 时出错: {str(e)}")
                # 保留NaN状态

    return all_ndvi, all_status


def save_station_data(station_idx, station_id, all_ndvi, all_status, time_index, output_path):
    """保存单个站点的数据"""
    station_id_str = str(station_id)
    station_file = output_path / f"NDVI_Station_{station_id_str}.nc"

    # 提取该站点的数据
    ndvi_series = all_ndvi[station_idx, :]
    status_series = all_status[station_idx, :]

    # 计算有效点数
    valid_points = np.sum(~np.isnan(ndvi_series))

    # 创建数据集
    ds_station = xr.Dataset(
        data_vars={
            'NDVI': (('time',), ndvi_series),
            'status': (('time',), status_series)
        },
        coords={'time': time_index}
    )

    # 设置属性
    ds_station.NDVI.attrs = {
        'long_name': 'Normalized Difference Vegetation Index',
        'units': 'dimensionless',
        'valid_range': [-1.0, 1.0],
        'description': 'NDVI calculated as (Albedo_04 - Albedo_03)/(Albedo_04 + Albedo_03)',
        'station_id': station_id
    }

    ds_station.status.attrs = {
        'long_name': 'Data availability status',
        'flag_values': [-1, 0, 1],
        'flag_meanings': 'night_or_missing daytime_available daytime_unavailable',
        'station_id': station_id
    }

    # 保存结果
    encoding = {
        'NDVI': {'zlib': True, 'complevel': 5},
        'status': {'zlib': True, 'complevel': 5, 'dtype': 'int8'}
    }
    ds_station.to_netcdf(station_file, encoding=encoding)

    # 返回站点ID和有效点数
    return station_id, valid_points


def main():
    """主函数：重组小时数据为站点时间序列"""
    # 创建输出目录
    output_path = Path(OUTPUT_DIR)
    output_path.mkdir(parents=True, exist_ok=True)

    # 创建临时目录
    temp_path = Path(TEMP_DIR)
    temp_path.mkdir(parents=True, exist_ok=True)

    # 获取所有站点
    stations = get_all_stations()
    num_stations = len(stations)
    logger.info(f"找到 {num_stations} 个站点")

    # 生成时间索引
    time_index = get_time_index()
    num_times = len(time_index)
    logger.info(f"时间范围: {start_date} 到 {end_date}, 共 {num_times} 个时间点")

    # 获取所有每日文件路径
    daily_files = get_daily_file_paths()
    all_days = sorted(daily_files.keys())

    # 检查恢复点
    processed_days = set()
    progress_file = temp_path / "progress.txt"
    if progress_file.exists():
        with open(progress_file, 'r') as f:
            for line in f:
                processed_days.add(datetime.strptime(line.strip(), '%Y-%m-%d'))
        logger.info(f"检测到恢复点，已处理 {len(processed_days)} 天")

    # 初始化全局数组
    global_ndvi = np.full((num_stations, num_times), np.nan, dtype=np.float32)
    global_status = np.full((num_stations, num_times), -1, dtype=np.int8)

    # 按批次处理每一天
    day_batches = []
    current_batch = {}

    for day in all_days:
        if day in processed_days:
            continue

        current_batch[day] = daily_files[day]

        if len(current_batch) >= DAILY_BATCH_SIZE:
            day_batches.append(current_batch)
            current_batch = {}

    if current_batch:
        day_batches.append(current_batch)

    # 处理每个批次
    for batch_idx, day_batch in enumerate(day_batches):
        logger.info(f"处理批次 {batch_idx + 1}/{len(day_batches)} (包含 {len(day_batch)} 天)")

        # 处理该批次
        batch_ndvi, batch_status = process_day_batch(day_batch, stations, time_index)

        # 更新全局数组
        for day in day_batch:
            # 获取该天的所有时间索引
            day_times = [t for t in time_index if t.date() == day.date()]
            time_indices = [np.where(time_index == t)[0][0] for t in day_times]

            # 更新全局数组
            for time_idx in time_indices:
                global_ndvi[:, time_idx] = batch_ndvi[:, time_idx]
                global_status[:, time_idx] = batch_status[:, time_idx]

        # 更新进度
        with open(progress_file, 'a') as f:
            for day in day_batch:
                f.write(day.strftime('%Y-%m-%d') + '\n')
        logger.info(f"批次 {batch_idx + 1} 完成，更新进度")

    # 并行保存所有站点数据
    logger.info("开始保存所有站点数据...")
    futures = []
    valid_counts = {station_id: 0 for station_id in stations}

    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for station_idx, station_id in enumerate(stations):
            future = executor.submit(
                save_station_data,
                station_idx, station_id,
                global_ndvi, global_status,
                time_index, output_path
            )
            futures.append(future)

        for future in as_completed(futures):
            try:
                station_id, valid_points = future.result()
                valid_counts[station_id] = valid_points
            except Exception as e:
                logger.error(f"保存站点数据时出错: {str(e)}")

    # 记录统计信息
    for station_id in stations:
        valid_points = valid_counts[station_id]
        logger.info(
            f"站点 {station_id} 有效数据点: {valid_points}/{num_times} "
            f"({valid_points / num_times:.1%})"
        )

    # 清理临时文件
    if progress_file.exists():
        os.remove(progress_file)
    shutil.rmtree(temp_path, ignore_errors=True)

    logger.info("所有站点处理完成!")


if __name__ == "__main__":
    main()