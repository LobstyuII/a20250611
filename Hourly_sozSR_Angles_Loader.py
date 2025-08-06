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

# 失效站点文件路径
DEPRECATED_STATION_FILE = r'D:\H8_data\Station_deprecated.nc'


def validate_file_path(year, month, day, hour, minute):
    """构建并验证文件路径"""
    date_str = f"{year}{month:02d}{day:02d}"
    l1toa_path = os.path.join(L1TOA_DIR, f"{year}", f"{month:02d}", f"H8_{date_str}_{hour:02d}{minute:02d}.nc")
    l2arp_path = os.path.join(L2ARP_DIR, f"{year}", f"{month:02d}", f"H8L2ARP_{date_str}_{hour:02d}{minute:02d}.nc")
    return l1toa_path if os.path.exists(l1toa_path) else None, l2arp_path if os.path.exists(l2arp_path) else None


def get_deprecated_mask(stations):
    """获取失效站点的掩码"""
    try:
        with nc.Dataset(DEPRECATED_STATION_FILE) as dep_ds:
            dep_stations = dep_ds.variables['Station'][:]
            # 直接使用字符串数组
            dep_stations = [str(station) for station in dep_stations]
            # 创建布尔掩码
            return np.array([stat in dep_stations for stat in stations], dtype=bool)
    except Exception as e:
        logger.error(f"加载失效站点文件失败: {e}")
        return np.zeros(len(stations), dtype=bool)


def process_hourly_data(start_date, end_date):
    """处理指定日期范围内的数据"""
    sample_file = os.path.join(L1TOA_DIR, f"{start_date.year}", f"{start_date.month:02d}",
                               f"H8_{start_date.year}{start_date.month:02d}{start_date.day:02d}_0000.nc")
    with nc.Dataset(sample_file) as ds:
        stations = ds.variables['Station'][:]
        stations = [str(station) for station in stations]

    deprecated_mask = get_deprecated_mask(stations)
    logger.info(f"标记失效站点数量: {np.sum(deprecated_mask)}")

    current_date = start_date

    while current_date <= end_date:
        year = current_date.year
        month = current_date.month
        day = current_date.day

        for hour in [*range(0, 12), *range(21, 24)]:
            logger.info(f"处理 {current_date.strftime('%Y%m%d')} {hour:02d}:00")

            band_accum = {band: np.zeros(STATION_COUNT, dtype=np.float32) for band in BANDS}
            band_count = {band: np.zeros(STATION_COUNT, dtype=np.uint8) for band in BANDS}
            angles_data = {angle: np.full(STATION_COUNT, np.nan, dtype=np.float32) for angle in ANGLES}
            station_valid = np.zeros(STATION_COUNT, dtype=bool)
            hourly_availability = np.ones(STATION_COUNT, dtype=np.int8)
            hourly_availability[deprecated_mask] = 1

            valid_time_points = 0

            for minute in [0, 10, 20, 30, 40, 50]:
                l1toa_path, l2arp_path = validate_file_path(year, month, day, hour, minute)

                if not l1toa_path or not l2arp_path:
                    logger.debug(f"文件缺失: {year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}")
                    continue

                try:
                    with nc.Dataset(l2arp_path) as l2ds:
                        avail = l2ds.variables['Data_Availability'][:]
                        landwater = l2ds.variables['Land_Water_Flag'][:]
                        cloud = l2ds.variables['Cloud_Flag'][:]
                        retrieval = l2ds.variables['Retrieval_Status'][:]
                        turbid_water = l2ds.variables['Turbid_Water'][:]
                        snow_ice = l2ds.variables['Snow_Ice'][:]
                        angle_threshold = l2ds.variables['Angle_Threshold'][:]
                        sunglint = l2ds.variables['Sunglint'][:]
                        add_cloud = l2ds.variables['Additional_Cloud_Flag'][:]

                        valid_l2arp = (avail == 0) & (landwater == 0) & (cloud == 0) & \
                                      (retrieval == 0) & (turbid_water == 0) & (snow_ice == 0) & \
                                      (angle_threshold == 0) & (sunglint == 0) & (add_cloud == 0)

                    with nc.Dataset(l1toa_path) as l1ds:
                        soz = l1ds.variables['SOZ'][:]
                        soz_valid = (soz < 65) & np.isfinite(soz)
                        valid_mask = valid_l2arp & soz_valid & ~deprecated_mask

                        for band in BANDS:
                            band_data = l1ds.variables[band][:]
                            valid_data = np.isfinite(band_data)
                            combined_mask = valid_mask & valid_data

                            band_accum[band][combined_mask] += band_data[combined_mask]
                            band_count[band][combined_mask] += 1
                            station_valid[combined_mask] = True

                        if minute == 30:
                            for angle in ANGLES:
                                angle_data = l1ds.variables[angle][:]
                                valid_angles = np.isfinite(angle_data) & ~deprecated_mask
                                angles_data[angle][valid_angles] = angle_data[valid_angles]

                    valid_time_points += 1
                    logger.debug(f"成功处理: {l1toa_path}")

                except Exception as e:
                    logger.error(f"处理文件时出错: {l1toa_path} | {e}")

            hourly_bands = {}
            for band in BANDS:
                avg = np.full(STATION_COUNT, np.nan, dtype=np.float32)
                valid_indices = band_count[band] > 0
                avg[valid_indices] = band_accum[band][valid_indices] / band_count[band][valid_indices]
                hourly_bands[band] = avg

            hourly_availability[station_valid] = 0

            if valid_time_points == 0:
                logger.warning(f"无有效时间点: {year}-{month:02d}-{day:02d} {hour:02d}:00")

            output_path = os.path.join(OUTPUT_DIR, f"{year}", f"{month:02d}")
            os.makedirs(output_path, exist_ok=True)
            output_file = os.path.join(output_path,
                                       f"H8_hourly_sozSR_angles_{year}{month:02d}{day:02d}_{hour:02d}00.nc")

            try:
                with nc.Dataset(output_file, 'w', format='NETCDF4') as out_ds:
                    out_ds.createDimension('Station', STATION_COUNT)

                    station_var = out_ds.createVariable('Station', str, ('Station',))
                    station_var[:] = np.array(stations, dtype=object)

                    for band in BANDS:
                        band_var = out_ds.createVariable(band, np.float32, ('Station',))
                        band_var[:] = hourly_bands[band]
                        band_var.units = "Reflectance"
                        band_var.long_name = f"Hourly average of {band}"

                    for angle in ANGLES:
                        angle_var = out_ds.createVariable(angle, np.float32, ('Station',))
                        angle_var[:] = angles_data[angle]
                        angle_var.units = "Degrees"
                        angle_var.long_name = f"Satellite/Solar angle at {hour:02d}:30"

                    avail_var = out_ds.createVariable('hourly_availability', np.int8, ('Station',))
                    avail_var[:] = hourly_availability
                    avail_var.long_name = "Hourly data availability"
                    avail_var.description = "0: valid; 1: invalid (deprecated or no valid data points)"

                    out_ds.time = f"{year}{month:02d}{day:02d}{hour:02d}00"
                    out_ds.title = "Himawari-8 Hourly sozSR & Angles POIs Dataset"
                    out_ds.source = f"Generated from {start_date} to {end_date}"
                    out_ds.creation_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    out_ds.valid_time_points = valid_time_points
                    out_ds.soz_threshold = "Solar zenith angle <65 degrees for valid daytime pixels"
                    out_ds.deprecated_stations = "Marked as availability=1"

                logger.info(f"创建输出文件: {output_file}")

            except Exception as e:
                logger.error(f"创建输出文件失败: {output_file} | {e}")

        current_date += timedelta(days=1)


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    start_date = datetime(2015, 7, 7)
    end_date = datetime(2021, 12, 31)
    logger.addHandler(logging.StreamHandler(sys.stdout))

    try:
        process_hourly_data(start_date, end_date)
        logger.info("处理完成!")
    except Exception as e:
        logger.exception("处理过程中发生严重错误")