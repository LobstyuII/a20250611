import ee
import numpy as np
import netCDF4 as nc
import xarray as xr
import os
import logging
from datetime import datetime
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)


def GEE_authorizing():
    """初始化GEE认证"""
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

        stations = ds['Station'].values
        lats = ds['Lat'].values
        lons = ds['Lon'].values

        return stations, lats, lons

    except Exception as e:
        logging.error(f"读取 LUTs.nc 文件失败: {e}")
        raise


def create_lc_nc(output_path, stations, lats, lons, years):
    """创建土地覆盖NC文件"""
    try:
        ds = nc.Dataset(output_path, 'w', format='NETCDF4')

        # 创建维度
        ds.createDimension('Station', len(stations))
        ds.createDimension('time', len(years))

        # 创建变量
        station_var = ds.createVariable('Station', str, ('Station',))
        lat_var = ds.createVariable('Lat', 'f4', ('Station',))
        lon_var = ds.createVariable('Lon', 'f4', ('Station',))
        time_var = ds.createVariable('time', 'i4', ('time',))
        lc_var = ds.createVariable('LC_type1', 'i2', ('time', 'Station'),
                                   fill_value=-9999, zlib=True)

        # 添加变量属性
        time_var.units = f"years since {min(years)}-01-01"
        time_var.calendar = "standard"
        lc_var.long_name = "IGBP Land Cover Type 1 Classification"
        lc_var.units = "class"
        lc_var.missing_value = -9999

        # 写入站点和坐标数据
        station_var[:] = stations
        lat_var[:] = lats
        lon_var[:] = lons
        time_var[:] = [year - min(years) for year in years]  # 相对年份

        # 添加全局属性
        ds.title = "MODIS MCD12Q1 Land Cover Classification (IGBP)"
        ds.history = f"Created on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ds.source = "Google Earth Engine: MODIS/061/MCD12Q1"
        ds.Conventions = "CF-1.8"

        logging.info(f"创建 NC 文件成功: {output_path}")
        return ds, lc_var

    except Exception as e:
        logging.error(f"创建 NC 文件失败: {e}")
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


def get_yearly_lc(year, poi_fc):
    """获取单一年份的土地覆盖数据"""
    try:
        # 获取年度土地覆盖影像
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"

        collection = ee.ImageCollection("MODIS/061/MCD12Q1") \
            .filterDate(start_date, end_date) \
            .select('LC_Type1')

        image = collection.first()

        if not image:
            logging.warning(f"{year} 没有可用数据")
            return None, None

        # 采样POI
        sampled = image.sampleRegions(
            collection=poi_fc,
            scale=500,  # MCD12Q1分辨率为500m
            geometries=False
        )

        # 获取采样结果
        sampled_info = sampled.getInfo()

        if not sampled_info or 'features' not in sampled_info:
            logging.warning(f"{year} 没有采样结果")
            return None, None

        # 提取数据
        lc_data = {}
        for feature in sampled_info['features']:
            station = feature['properties']['Station']
            lc_value = feature['properties'].get('LC_Type1', -9999)
            lc_data[station] = lc_value

        return year, lc_data

    except Exception as e:
        logging.error(f"处理 {year} 年数据失败: {e}")
        return None, None


def main():
    # 初始化GEE
    GEE_authorizing()

    # 配置路径和参数
    data_path = "D:/H8_data"
    luts_path = os.path.join(data_path, "LUTs.nc")
    output_path = os.path.join(data_path, "LC_2015_2024.nc")
    years = list(range(2015, 2025))  # 2015-2024

    # 读取站点信息
    stations, lats, lons = read_luts_nc(luts_path)
    logging.info(f"共读取 {len(stations)} 个站点")

    # 创建输出文件
    ds_out, lc_var = create_lc_nc(output_path, stations, lats, lons, years)

    # 创建FeatureCollection
    poi_fc = get_feature_collection(stations, lats, lons)

    # 按年处理土地覆盖数据
    station_index = {station: idx for idx, station in enumerate(stations)}

    for year_idx, year in enumerate(tqdm(years, desc="处理年份")):
        year, lc_data = get_yearly_lc(year, poi_fc)

        if not lc_data:
            # 填充缺失值
            lc_var[year_idx, :] = np.full(len(stations), -9999)
            continue

        # 按站点顺序整理数据
        sorted_lc = []
        for station in stations:
            sorted_lc.append(lc_data.get(station, -9999))

        # 写入NC文件
        lc_var[year_idx, :] = np.array(sorted_lc)

    # 关闭文件
    ds_out.close()
    logging.info(f"处理完成! 文件已保存至: {output_path}")


if __name__ == "__main__":
    main()