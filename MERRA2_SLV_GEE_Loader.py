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


def save_hourly_merra_data(dt, to3_data, tqv_data, stations, lats, lons, base_path):
    """保存单小时MERRA-2数据到单独的NC文件（修复格式问题）"""
    try:
        if isinstance(dt, np.datetime64):
            dt = pd.Timestamp(dt).to_pydatetime()

        # 创建年月目录
        year = dt.strftime("%Y")
        month = dt.strftime("%m")
        dir_path = os.path.join(base_path, "MERRA2", year, month)
        os.makedirs(dir_path, exist_ok=True)

        # 文件命名格式为hhmm，包含TO3和TQV
        filename = f"MERRA2_{dt.strftime('%Y%m%d_%H%M')}_TO3_TQV.nc"
        file_path = os.path.join(dir_path, filename)

        # 检查文件是否已存在且完整
        if os.path.exists(file_path) and os.path.getsize(file_path) > 2048:
            logging.info(f"文件已存在: {filename}")
            return True

        # 删除可能已损坏的现有文件
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logging.warning(f"删除不完整文件: {filename}")
            except Exception as e:
                logging.error(f"删除文件失败: {e}")

        # 创建新的NC文件 - 修复格式问题
        with nc.Dataset(file_path, 'w', format='NETCDF4') as ds:
            # 定义维度 - 仅保留Station维度
            ds.createDimension('Station', len(stations))

            # 计算最大字符串长度
            max_str_len = max(len(str(s)) for s in stations) + 1

            # 定义变量 - 修复：使用一维数组
            station_var = ds.createVariable('Station', f'S{max_str_len}', ('Station',))
            lat_var = ds.createVariable('Lat', 'f4', ('Station',))
            lon_var = ds.createVariable('Lon', 'f4', ('Station',))
            to3_var = ds.createVariable('TO3', 'f4', ('Station',), fill_value=-9999.0)
            tqv_var = ds.createVariable('TQV', 'f4', ('Station',), fill_value=-9999.0)

            # 设置全局时间属性
            ds.setncattr('time', dt.strftime('%Y-%m-%d %H:%M:%S'))
            ds.setncattr('datetime', dt.isoformat())

            # 设置变量属性
            to3_var.long_name = 'Total Ozone Column'
            to3_var.units = 'Dobson Units'
            tqv_var.long_name = 'Total Precipitable Water Vapor'
            tqv_var.units = 'kg/m^2'

            # 写入数据 - 修复：直接使用一维数组
            station_arr = np.array([np.bytes_(str(s)) for s in stations], dtype=f'S{max_str_len}')
            station_var[:] = station_arr
            lat_var[:] = lats
            lon_var[:] = lons
            to3_var[:] = to3_data
            tqv_var[:] = tqv_data

        return True
    except Exception as e:
        logging.error(f"保存 {dt} 数据失败: {e}")
        traceback.print_exc()

        # 尝试删除可能不完整的文件
        if 'file_path' in locals() and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logging.info(f"已删除不完整文件: {file_path}")
            except:
                pass

        return False


def process_hourly_merra_data(dt, collection, poi_fc, stations, lats, lons, base_path, max_retries=5):
    """处理单小时MERRA-2数据并保存（带重试机制）"""
    retry_count = 0
    while retry_count < max_retries:
        try:
            if isinstance(dt, np.datetime64):
                dt = pd.Timestamp(dt).to_pydatetime()

            # MERRA-2时间范围（小时数据）
            start_dt = dt.strftime('%Y-%m-%dT%H:%M:%S')
            end_dt = (dt + datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S')

            # 获取该小时数据
            image = collection.filterDate(start_dt, end_dt).first()

            if image is None:
                logging.warning(f"{start_dt} 没有数据")
                return False

            # 选择TO3和TQV波段
            image = image.select(['TO3', 'TQV'])

            # 采样POI
            sampled = image.sampleRegions(
                collection=poi_fc,
                scale=1000,  # MERRA-2分辨率约50km，使用1000m采样
                geometries=False
            )

            # 获取采样结果
            sampled_dict = sampled.getInfo()

            if 'features' not in sampled_dict or len(sampled_dict['features']) == 0:
                logging.warning(f"{start_dt} 没有采样结果")
                return False

            # 提取TO3和TQV数据
            to3_data = []
            tqv_data = []
            station_ids = []

            for feature in sampled_dict['features']:
                props = feature['properties']
                station_ids.append(props['Station'])
                to3_value = props.get('TO3', -9999.0)
                tqv_value = props.get('TQV', -9999.0)
                to3_data.append(to3_value)
                tqv_data.append(tqv_value)

            # 按原始站点顺序排序
            sorted_to3 = []
            sorted_tqv = []
            for station in stations:
                if station in station_ids:
                    idx = station_ids.index(station)
                    sorted_to3.append(to3_data[idx])
                    sorted_tqv.append(tqv_data[idx])
                else:
                    sorted_to3.append(-9999.0)
                    sorted_tqv.append(-9999.0)

            # 保存数据
            return save_hourly_merra_data(dt, sorted_to3, sorted_tqv, stations, lats, lons, base_path)

        except ee.EEException as e:
            retry_count += 1
            logging.warning(f"GEE错误 ({e})，重试 {retry_count}/{max_retries}")
            time.sleep(10 * retry_count)
        except Exception as e:
            retry_count += 1
            logging.error(f"处理 {dt} 时出错: {e}，重试 {retry_count}/{max_retries}")
            time.sleep(5)
            traceback.print_exc()

    logging.error(f"处理 {dt} 失败，已达到最大重试次数")
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
    data_path = "D:/H8_data"  # 修改为您的数据存储路径
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

    # 定义MERRA-2 ImageCollection
    collection = ee.ImageCollection("NASA/GSFC/MERRA/slv/2")
    logging.info("MERRA-2 数据集加载成功")

    # 准备任务队列
    tasks = []
    for dt in hourly_times:
        if isinstance(dt, np.datetime64):
            py_dt = pd.Timestamp(dt).to_pydatetime()
        else:
            py_dt = dt

        year = py_dt.strftime("%Y")
        month = py_dt.strftime("%m")
        filename = f"MERRA2_{py_dt.strftime('%Y%m%d_%H%M')}_TO3_TQV.nc"
        file_path = os.path.join(data_path, "MERRA2", year, month, filename)

        # 检查文件是否需要下载
        if not os.path.exists(file_path) or os.path.getsize(file_path) <= 2048:
            tasks.append(dt)

    logging.info(f"总时间点: {len(hourly_times)}, 已存在: {len(hourly_times) - len(tasks)}, 待处理: {len(tasks)}")

    # 使用线程池并行处理
    success_count = 0
    failed_count = 0
    total_tasks = len(tasks)

    # 设置并行线程数
    max_workers = 4

    with tqdm(total=total_tasks, desc="下载MERRA-2数据") as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(
                process_hourly_merra_data,
                dt, collection, poi_fc, stations, lats, lons, data_path
            ): dt for dt in tasks}

            for future in concurrent.futures.as_completed(futures):
                dt = futures[future]
                try:
                    if future.result():
                        success_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    logging.error(f"任务处理异常: {e}")
                    failed_count += 1
                pbar.update(1)
                pbar.set_postfix_str(f"成功: {success_count}, 失败: {failed_count}")

    logging.info(f"处理完成! 成功: {success_count}, 失败: {failed_count}, 总数: {total_tasks}")


def merge_merra_data(base_path, output_path):
    """合并所有小时MERRA-2数据到单个NetCDF文件（更新为处理新格式）"""
    try:
        all_files = []
        merra_dir = os.path.join(base_path, "MERRA2")

        for root, dirs, files in os.walk(merra_dir):
            for file in files:
                if file.endswith(".nc") and file.startswith("MERRA2_") and "TO3_TQV" in file:
                    all_files.append(os.path.join(root, file))

        if not all_files:
            logging.error("未找到MERRA-2数据文件")
            return

        logging.info(f"找到 {len(all_files)} 个数据文件，开始合并...")
        all_files.sort()

        # 初始化数据集列表
        ds_list = []
        time_values = []

        for file in tqdm(all_files, desc="合并MERRA-2文件"):
            try:
                # 从全局属性获取时间
                with nc.Dataset(file) as ds:
                    time_str = ds.getncattr('datetime')
                    dt = datetime.datetime.fromisoformat(time_str)

                # 打开为xarray数据集
                ds = xr.open_dataset(file)

                # 添加时间坐标
                ds = ds.assign_coords(time=dt)
                ds = ds.expand_dims('time')

                ds_list.append(ds)
            except Exception as e:
                logging.warning(f"无法打开或处理文件 {file}: {e}")

        if not ds_list:
            logging.error("没有有效文件可合并")
            return

        # 沿时间维度合并
        combined = xr.concat(ds_list, dim="time")

        # 设置时间变量属性
        combined.time.encoding['units'] = 'hours since 1980-01-01 00:00:00'
        combined.time.encoding['calendar'] = 'standard'

        # 保存合并后的数据集
        combined.to_netcdf(output_path)
        logging.info(f"成功合并数据到: {output_path}")

        # 验证文件
        try:
            ds = xr.open_dataset(output_path)
            logging.info(f"合并后数据集信息: \n{ds}")
            ds.close()
        except Exception as e:
            logging.error(f"验证输出文件失败: {e}")

    except Exception as e:
        logging.error(f"合并数据失败: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    # 第一步：下载数据
    main()

    # 第二步：合并数据（在下载完成后运行）
    # data_path = "D:/H8_data"
    # output_nc = os.path.join(data_path, "MERRA2_TO3_TQV_combined.nc")
    # merge_merra_data(data_path, output_nc)