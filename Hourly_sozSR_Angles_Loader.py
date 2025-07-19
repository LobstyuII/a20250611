import netCDF4 as nc
import numpy as np
import os
import glob
from datetime import datetime, timedelta
import logging
import sys

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# 配置路径和参数
L1TOA_DIR = r'D:\H8_data\H8L1'
L2ARP_DIR = r'D:\H8_data\H8L2ARP'
OUTPUT_DIR = r'D:\H8_data\Hourly_sozSR_Angles'
STATION_COUNT = 2014
BANDS = ['Albedo_01', 'Albedo_02', 'Albedo_03', 'Albedo_04', 'Albedo_05', 'Albedo_06']
ANGLES = ['SAZ', 'SAA', 'SOZ', 'SOA']


def validate_file_path(year, month, day, hour, minute):
    """构建并验证文件路径"""
    # 创建日期字符串 (YYYYMMDD)
    date_str = f"{year}{month:02d}{day:02d}"

    # 定义文件路径模式
    l1toa_path = os.path.join(L1TOA_DIR, f"{year}", f"{month:02d}", f"H8_{date_str}_{hour:02d}{minute:02d}.nc")
    l2arp_path = os.path.join(L2ARP_DIR, f"{year}", f"{month:02d}", f"H8L2ARP_{date_str}_{hour:02d}{minute:02d}.nc")

    return l1toa_path if os.path.exists(l1toa_path) else None, l2arp_path if os.path.exists(l2arp_path) else None


def process_hourly_data(start_date, end_date):
    """处理指定日期范围内的数据"""
    # 获取站点名称
    sample_file = os.path.join(L1TOA_DIR, f"{start_date.year}", f"{start_date.month:02d}", f"H8_{start_date.year}{start_date.month:02d}{start_date.day:02d}_0000.nc")
    with nc.Dataset(sample_file) as ds:
        stations = ds.variables['Station'][:]

    current_date = start_date

    while current_date <= end_date:
        year = current_date.year
        month = current_date.month
        day = current_date.day

        for hour in [*range(0, 12), *range(21, 23)]:
            logger.info(f"处理 {current_date.strftime('%Y%m%d')} {hour:02d}:00")

            # 初始化数据结构
            band_accum = {band: np.zeros(STATION_COUNT, dtype=np.float32) for band in BANDS}
            band_count = {band: np.zeros(STATION_COUNT, dtype=np.uint8) for band in BANDS}  # 独立计数器
            angles_data = {angle: np.full(STATION_COUNT, np.nan, dtype=np.float32) for angle in ANGLES}
            station_valid = np.zeros(STATION_COUNT, dtype=bool)  # 站点级有效标记
            hourly_availability = np.ones(STATION_COUNT, dtype=np.int8)  # 默认1:无效

            # 新增: 太阳高度角无效标记
            soz_invalid_mask = np.zeros(STATION_COUNT, dtype=bool)  # 标记SOZ≥65的站点

            # 处理6个时间点(00, 10, 20, 30, 40, 50)
            valid_time_points = 0

            for minute in [0, 10, 20, 30, 40, 50]:
                # 获取文件路径
                l1toa_path, l2arp_path = validate_file_path(year, month, day, hour, minute)

                # 确保两个文件都存在
                if not l1toa_path or not l2arp_path:
                    logger.debug(f"文件缺失: {year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}")
                    continue

                try:
                    # 1. 加载L2ARP数据
                    with nc.Dataset(l2arp_path) as l2ds:
                        avail = l2ds.variables['Data_Availability'][:]
                        landwater = l2ds.variables['Land_Water_Flag'][:]
                        cloud = l2ds.variables['Cloud_Flag'][:]

                    # 2. 加载L1TOA数据
                    with nc.Dataset(l1toa_path) as l1ds:
                        # 检查太阳高度角(SOZ)
                        soz = l1ds.variables['SOZ'][:]
                        soz_valid = (soz < 65) & np.isfinite(soz)  # SOZ<65且有效

                        # 计算综合可用性 (0=可用)，添加SOZ条件
                        valid_mask = (avail == 0) & (landwater == 0) & (cloud == 0) & soz_valid

                        # 记录SOZ无效的站点（用于最终标记）
                        soz_invalid_mask |= (soz >= 65) & np.isfinite(soz)  # 标记SOZ≥65的站点

                        # 处理波段数据
                        for band in BANDS:
                            band_data = l1ds.variables[band][:]
                            # 确保数据有效且不为NaN
                            valid_data = np.isfinite(band_data)
                            combined_mask = valid_mask & valid_data

                            band_accum[band][combined_mask] += band_data[combined_mask]
                            band_count[band][combined_mask] += 1  # 更新当前波段计数器
                            station_valid[combined_mask] = True  # 标记有效站点

                        # 如果是30分钟时间点，记录角度
                        if minute == 30:
                            for angle in ANGLES:
                                angle_data = l1ds.variables[angle][:]
                                # 确保角度数据有效
                                valid_angles = np.isfinite(angle_data)
                                angles_data[angle][valid_angles] = angle_data[valid_angles]

                    valid_time_points += 1
                    logger.debug(f"成功处理: {l1toa_path}")

                except Exception as e:
                    logger.error(f"处理文件时出错: {l1toa_path} | {e}")

            # 3. 计算小时平均值和可用性
            hourly_bands = {}
            for band in BANDS:
                avg = np.full(STATION_COUNT, np.nan, dtype=np.float32)
                valid_indices = band_count[band] > 0  # 关键：使用当前波段的计数器
                avg[valid_indices] = band_accum[band][valid_indices] / band_count[band][valid_indices]
                hourly_bands[band] = avg

            # 设置可用性:
            # - 至少有一个有效时间点则为可用(0)
            # - 太阳高度角≥65度则标记为-1
            hourly_availability[station_valid] = 0
            hourly_availability[soz_invalid_mask] = -1  # 覆盖其他标记

            # 如果没有任何有效时间点，记录警告
            if valid_time_points == 0:
                logger.warning(f"无有效时间点: {year}-{month:02d}-{day:02d} {hour:02d}:00")

            # 4. 创建输出文件
            output_path = os.path.join(OUTPUT_DIR, f"{year}", f"{month:02d}")
            os.makedirs(output_path, exist_ok=True)
            output_file = os.path.join(output_path, f"H8_hourly_sozSR_angles_{year}{month:02d}{day:02d}_{hour:02d}00.nc")

            try:
                with nc.Dataset(output_file, 'w', format='NETCDF4') as out_ds:
                    # 创建维度
                    out_ds.createDimension('Station', STATION_COUNT)

                    # 添加变量
                    station_var = out_ds.createVariable('Station', str, ('Station',))
                    station_var[:] = np.array(stations, dtype=object)  # 处理字符串数组

                    # 添加波段数据
                    for band in BANDS:
                        band_var = out_ds.createVariable(band, np.float32, ('Station',))
                        band_var[:] = hourly_bands[band]
                        band_var.units = "Reflectance"
                        band_var.long_name = f"Hourly average of {band}"

                    # 添加角度数据
                    for angle in ANGLES:
                        angle_var = out_ds.createVariable(angle, np.float32, ('Station',))
                        angle_var[:] = angles_data[angle]
                        angle_var.units = "Degrees"
                        angle_var.long_name = f"Satellite/Solar angle at {hour:02d}:30"

                    # 添加可用性变量 (更新描述)
                    avail_var = out_ds.createVariable('hourly_availability', np.int8, ('Station',))
                    avail_var[:] = hourly_availability
                    avail_var.long_name = "Hourly data availability"
                    avail_var.description = "0: valid; 1: invalid (no valid 10-min data points); -1: solar zenith angle >=65"

                    # 添加全局属性
                    out_ds.time = f"{year}{month:02d}{day:02d}{hour:02d}00"
                    out_ds.title = "Himawari-8 Hourly sozSR & Angles POIs Dataset"
                    out_ds.source = f"Generated from {start_date} to {end_date}"
                    out_ds.creation_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    out_ds.valid_time_points = valid_time_points
                    out_ds.soz_threshold = "Solar zenith angle <65 degrees for valid daytime pixels"

                logger.info(f"创建输出文件: {output_file}")

            except Exception as e:
                logger.error(f"创建输出文件失败: {output_file} | {e}")

        # 移动到下一天
        current_date += timedelta(days=1)


if __name__ == "__main__":
    # 创建输出目录
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 设置日期范围
    start_date = datetime(2015, 7, 7)
    end_date = datetime(2015, 12, 31)

    # 添加详细日志
    logger.addHandler(logging.StreamHandler(sys.stdout))

    # 处理数据
    try:
        process_hourly_data(start_date, end_date)
        logger.info("处理完成!")
    except Exception as e:
        logger.exception("处理过程中发生严重错误")