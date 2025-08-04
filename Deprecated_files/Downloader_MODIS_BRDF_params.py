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
    """从LUTs.nc文件中读取站点信息"""
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


def get_himawari_grid(lon, lat):
    """
    计算Himawari 5km网格的边界和索引
    公式:
        longitude = 80 + x * 0.05
        latitude = 60 - y * 0.05
    """
    # 计算网格索引
    x_index = math.floor((lon - 80) / 0.05)
    y_index = math.floor((60 - lat) / 0.05)

    # 计算网格边界
    west = 80 + x_index * 0.05
    east = west + 0.05
    north = 60 - y_index * 0.05
    south = north - 0.05

    return west, south, east, north, x_index, y_index


def get_feature_collection(stations, lats, lons):
    """创建Himawari 5km网格的FeatureCollection"""
    try:
        features = []
        grid_info = []  # 存储网格索引信息

        for station, lat, lon in zip(stations, lats, lons):
            # 计算Himawari网格
            west, south, east, north, x_index, y_index = get_himawari_grid(lon, lat)

            # 创建矩形特征
            rect = ee.Geometry.Rectangle([west, south, east, north])
            feature = ee.Feature(
                rect,
                {
                    'Station': station,
                    'grid_x': x_index,
                    'grid_y': y_index
                }
            )
            features.append(feature)
            grid_info.append((x_index, y_index))

        fc = ee.FeatureCollection(features)
        logging.info("成功创建Himawari网格FeatureCollection")
        return fc, grid_info

    except Exception as e:
        logging.error(f"创建FeatureCollection失败: {e}")
        raise


def save_daily_brdf_data(date, brdf_data, stations, lats, lons, grid_info, base_path):
    """保存单日BRDF数据到NC文件"""
    try:
        # 创建年月目录
        year = date.strftime("%Y")
        month = date.strftime("%m")
        dir_path = os.path.join(base_path, "MODIS_BRDFparams", year, month)
        os.makedirs(dir_path, exist_ok=True)

        # 文件路径
        filename = f"MODIS_BRDFparams_{date.strftime('%Y%m%d')}.nc"
        file_path = os.path.join(dir_path, filename)

        # 如果文件已存在且完整，则跳过
        if os.path.exists(file_path) and os.path.getsize(file_path) > 1024:
            logging.info(f"文件已存在: {file_path}")
            return True

        # 创建新的NC文件
        with nc.Dataset(file_path, 'w', format='NETCDF4') as ds:
            # 定义维度（只有站点维度）
            ds.createDimension('Station', len(stations))

            # 定义变量
            station_var = ds.createVariable('Station', str, ('Station',))
            lat_var = ds.createVariable('Lat', 'f4', ('Station',))
            lon_var = ds.createVariable('Lon', 'f4', ('Station',))

            # 创建BRDF参数变量
            band1_iso = ds.createVariable('Band1_iso', 'f4', ('Station',), fill_value=-9999.0)
            band1_vol = ds.createVariable('Band1_vol', 'f4', ('Station',), fill_value=-9999.0)
            band1_geo = ds.createVariable('Band1_geo', 'f4', ('Station',), fill_value=-9999.0)
            band2_iso = ds.createVariable('Band2_iso', 'f4', ('Station',), fill_value=-9999.0)
            band2_vol = ds.createVariable('Band2_vol', 'f4', ('Station',), fill_value=-9999.0)
            band2_geo = ds.createVariable('Band2_geo', 'f4', ('Station',), fill_value=-9999.0)

            # 新增网格索引变量
            gridx_var = ds.createVariable('grid_x', 'i4', ('Station',))
            gridy_var = ds.createVariable('grid_y', 'i4', ('Station',))

            # 添加日期作为全局属性
            ds.date = date.strftime("%Y-%m-%d")

            # 写入站点数据
            station_var[:] = np.array(stations, dtype=object)
            lat_var[:] = lats
            lon_var[:] = lons

            # 写入网格索引数据
            gridx = [g[0] for g in grid_info]
            gridy = [g[1] for g in grid_info]
            gridx_var[:] = gridx
            gridy_var[:] = gridy

            # 写入BRDF数据
            band1_iso[:] = brdf_data.get('Band1_iso', [-9999.0] * len(stations))
            band1_vol[:] = brdf_data.get('Band1_vol', [-9999.0] * len(stations))
            band1_geo[:] = brdf_data.get('Band1_geo', [-9999.0] * len(stations))
            band2_iso[:] = brdf_data.get('Band2_iso', [-9999.0] * len(stations))
            band2_vol[:] = brdf_data.get('Band2_vol', [-9999.0] * len(stations))
            band2_geo[:] = brdf_data.get('Band2_geo', [-9999.0] * len(stations))

        logging.info(f"成功保存: {file_path}")
        return True

    except Exception as e:
        logging.error(f"保存 {date} BRDF数据失败: {e}")
        traceback.print_exc()
        return False


def extract_qa_flag(qa_value, bit_start, bit_end):
    """提取QA标志位"""
    mask = (1 << (bit_end - bit_start + 1)) - 1
    return (qa_value >> bit_start) & mask


def filter_brdf_quality(img):
    """根据MCD43A2 QA标志过滤数据"""
    # 提取QA波段
    qa = img.select('QA')

    # 提取波段1和波段2的QA标志（0-2位: 波段1, 3-5位: 波段2）
    band1_qa = qa.bitwiseAnd(7)  # 二进制111 = 7
    band2_qa = qa.rightShift(3).bitwiseAnd(7)

    # 创建质量掩码（只保留0和1）
    band1_mask = band1_qa.lte(1)
    band2_mask = band2_qa.lte(1)

    # 应用掩码到BRDF参数
    band1_params = img.select(['Band1_iso', 'Band1_vol', 'Band1_geo']).updateMask(band1_mask)
    band2_params = img.select(['Band2_iso', 'Band2_vol', 'Band2_geo']).updateMask(band2_mask)

    return band1_params.addBands(band2_params)


def process_daily_brdf_data(date, brdf_col, grid_fc, stations, lats, lons, grid_info, base_path, max_retries=5):
    """处理单日BRDF数据"""
    retry_count = 0
    while retry_count < max_retries:
        try:
            # 设置日期范围（UTC时间）
            start_date = datetime.datetime(date.year, date.month, date.day, 0, 0, 0)
            end_date = start_date + datetime.timedelta(days=1)

            # 获取当天的BRDF数据
            brdf_img = brdf_col.filterDate(start_date, end_date).first()

            # 初始化结果字典
            brdf_data = {
                'Band1_iso': [-9999.0] * len(stations),
                'Band1_vol': [-9999.0] * len(stations),
                'Band1_geo': [-9999.0] * len(stations),
                'Band2_iso': [-9999.0] * len(stations),
                'Band2_vol': [-9999.0] * len(stations),
                'Band2_geo': [-9999.0] * len(stations)
            }

            if brdf_img:
                # 应用QA过滤
                filtered_img = filter_brdf_quality(brdf_img)

                # 定义要提取的波段
                bands = ['Band1_iso', 'Band1_vol', 'Band1_geo',
                         'Band2_iso', 'Band2_vol', 'Band2_geo']

                # 区域统计
                reduced = filtered_img.reduceRegions(
                    collection=grid_fc,
                    reducer=ee.Reducer.mean(),
                    scale=500  # MODIS原始分辨率
                )

                # 获取结果
                result_info = reduced.getInfo()

                if 'features' in result_info:
                    # 构建站点到BRDF参数的映射
                    temp_data = {band: {} for band in bands}

                    for f in result_info['features']:
                        props = f['properties']
                        station = props['Station']

                        for band in bands:
                            value = props.get(band, -9999.0)
                            if value is None:
                                value = -9999.0
                            temp_data[band][station] = value

                    # 转换为站点顺序列表
                    for band in bands:
                        brdf_data[band] = [temp_data[band].get(station, -9999.0) for station in stations]

            # 保存数据
            return save_daily_brdf_data(date, brdf_data, stations, lats, lons, grid_info, base_path)

        except Exception as e:
            retry_count += 1
            error_type = type(e).__name__
            logging.warning(f"处理 {date} 时出错 ({error_type}): {e}，重试 {retry_count}/{max_retries}")
            time.sleep(5 * retry_count)  # 指数退避等待

            if retry_count >= max_retries:
                logging.error(f"处理 {date} 失败，已达到最大重试次数")
                traceback.print_exc()
                return False


def main_brdf():
    # 初始化 GEE
    GEE_authorizing()

    # 数据路径
    data_path = r"D:/H8_data"
    luts_path = os.path.join(data_path, "LUTs.nc")

    # 读取LUTs.nc文件
    stations, lats, lons = read_luts_nc(luts_path)
    logging.info(f"共读取 {len(stations)} 个站点")

    # 创建Himawari网格FeatureCollection
    grid_fc, grid_info = get_feature_collection(stations, lats, lons)

    # 定义BRDF ImageCollection（组合A1和A2）
    mcd43a1 = ee.ImageCollection("MODIS/061/MCD43A1")
    mcd43a2 = ee.ImageCollection("MODIS/061/MCD43A2")

    # 选择所需波段并合并
    brdf_col = mcd43a1.select(
        ['BRDF_Albedo_Parameters_Band1_iso', 'BRDF_Albedo_Parameters_Band1_vol', 'BRDF_Albedo_Parameters_Band1_geo',
         'BRDF_Albedo_Parameters_Band2_iso', 'BRDF_Albedo_Parameters_Band2_vol', 'BRDF_Albedo_Parameters_Band2_geo']
    ).map(lambda img: img.rename(['Band1_iso', 'Band1_vol', 'Band1_geo', 'Band2_iso', 'Band2_vol', 'Band2_geo']))

    qa_col = mcd43a2.select(
        ['BRDF_Albedo_Band_Quality_Band1', 'BRDF_Albedo_Band_Quality_Band2']
    ).map(lambda img: img.rename(['Band1_qa', 'Band2_qa']))

    # 修改后的合并QA到BRDF数据集
    def combine_qa(brdf_img):
        date = brdf_img.date()
        qa_img = qa_col.filterDate(date, date.advance(1, 'day')).first()

        # 如果找到QA图像，则合并
        if qa_img:
            # 将两个QA波段合并为一个整数波段
            band1_qa = qa_img.select('Band1_qa')
            band2_qa = qa_img.select('Band2_qa')

            # 将band2_qa左移3位，然后与band1_qa进行按位或
            combined_qa = band1_qa.bitwiseOr(band2_qa.leftShift(3))
            combined_qa = combined_qa.rename('QA')

            return brdf_img.addBands(combined_qa).set('system:time_start', brdf_img.get('system:time_start'))
        else:
            # 如果没有QA图像，则创建一个填充0的QA波段
            qa_band = ee.Image(0).rename('QA')
            return brdf_img.addBands(qa_band).set('system:time_start', brdf_img.get('system:time_start'))

    # 修改后的BRDF集合创建
    brdf_col = brdf_col.map(combine_qa).select(
        ['Band1_iso', 'Band1_vol', 'Band1_geo',
         'Band2_iso', 'Band2_vol', 'Band2_geo', 'QA'],
        ['Band1_iso', 'Band1_vol', 'Band1_geo',
         'Band2_iso', 'Band2_vol', 'Band2_geo', 'QA']
    )

    logging.info("已初始化MCD43A1和MCD43A2集合")

    # 设置日期范围
    start_date = datetime.date(2015, 7, 7)
    end_date = datetime.date(2024, 12, 31)

    # 生成日期序列
    unique_dates = []
    current_date = start_date
    while current_date <= end_date:
        unique_dates.append(current_date)
        current_date += datetime.timedelta(days=1)

    logging.info(f"日期范围: {start_date} 到 {end_date}, 共 {len(unique_dates)} 天")

    # 准备任务队列
    tasks = []
    for date in unique_dates:
        # 检查文件是否已存在
        year = date.strftime("%Y")
        month = date.strftime("%m")
        filename = f"MODIS_BRDFparams_{date.strftime('%Y%m%d')}.nc"
        file_path = os.path.join(data_path, "MODIS_BRDFparams", year, month, filename)

        # 如果文件不存在或不完整，则加入任务队列
        if not os.path.exists(file_path) or os.path.getsize(file_path) <= 1024:
            tasks.append(date)

    logging.info(f"总日期数: {len(unique_dates)}, 已存在: {len(unique_dates) - len(tasks)}, 待处理: {len(tasks)}")

    # 使用线程池并行处理
    success_count = 0
    failed_count = 0
    total_tasks = len(tasks)

    # 设置并行线程数
    max_workers = 5

    with tqdm(total=total_tasks, desc="下载进度") as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            futures = {executor.submit(
                process_daily_brdf_data,
                date, brdf_col, grid_fc, stations, lats, lons, grid_info, data_path
            ): date for date in tasks}

            # 处理完成的任务
            for future in concurrent.futures.as_completed(futures):
                date = futures[future]
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
    main_brdf()