import os
import time
import netCDF4 as nc
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
from Py6S import *

# 配置路径 - 请根据实际文件位置修改
PATHS = {
    "h8_l1": "D:/H8_data/h8l1/",  # H8 L1 TOA数据目录
    "h8_l2arp": "D:/H8_data/h8l2arp/",  # H8 L2 ARP AOD数据目录
    "mcd12q1": "data/mcd12q1/",  # MCD12Q1 LC数据目录
    "mod08": "data/poi_mod08/",  # MOD08大气数据目录
    "output": "output/poi_6s_nc/",  # 输出目录
    "stations": "Air_stations_lon_lat.csv"  # 站点坐标文件
}

# 波段参数
BAND_WAVELENGTHS = [0.47, 0.51, 0.64, 0.86, 1.6, 2.3]
BAND_NAMES = [f"Albedo_0{i + 1}" for i in range(1, 7)]
SR_BAND_NAMES = [f"SR_0{i + 1}" for i in range(1, 7)]

# 日期范围
START_DATE = datetime(2015, 7, 11)
END_DATE = datetime(2021, 12, 31)

# LUCC到BRDF参数的映射
LUCC_TO_BRDF = {
    1: {"model": "Rahman", "intensity": 0.3, "asymmetry": 0.1, "structural": 0.5},  # 常绿针叶林
    2: {"model": "Rahman", "intensity": 0.35, "asymmetry": 0.12, "structural": 0.55},  # 常绿阔叶林
    3: {"model": "Rahman", "intensity": 0.25, "asymmetry": 0.08, "structural": 0.45},  # 落叶针叶林
    4: {"model": "Rahman", "intensity": 0.3, "asymmetry": 0.1, "structural": 0.5},  # 落叶阔叶林
    5: {"model": "Rahman", "intensity": 0.2, "asymmetry": 0.05, "structural": 0.4},  # 混交林
    6: {"model": "Rahman", "intensity": 0.4, "asymmetry": 0.15, "structural": 0.6},  # 稠密灌丛
    7: {"model": "Rahman", "intensity": 0.35, "asymmetry": 0.12, "structural": 0.55},  # 稀疏灌丛
    8: {"model": "Walthall", "param1": 0.5, "param2": 0.2, "param3": 0.1, "albedo": 0.25},  # 稀树草原
    9: {"model": "Walthall", "param1": 0.4, "param2": 0.15, "param3": 0.05, "albedo": 0.3},  # 草地
    10: {"model": "Lambertian", "albedo": 0.35},  # 永久湿地
    11: {"model": "Lambertian", "albedo": 0.1},  # 农田
    12: {"model": "Lambertian", "albedo": 0.4},  # 城市建筑
    13: {"model": "Walthall", "param1": 0.6, "param2": 0.25, "param3": 0.15, "albedo": 0.35},  # 农田/自然植被
    14: {"model": "Lambertian", "albedo": 0.7},  # 冰雪
    15: {"model": "Lambertian", "albedo": 0.05},  # 裸地
    16: {"model": "Lambertian", "albedo": 0.02},  # 水体
    17: {"model": "Lambertian", "albedo": 0.02},  # 水体
    255: {"model": "Lambertian", "albedo": 0.2}  # 默认
}


def get_current_timestamp():
    """获取当前时间戳"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_netcdf_data(file_path, variables):
    """加载NetCDF文件数据"""
    if not os.path.exists(file_path):
        return None

    try:
        with nc.Dataset(file_path) as ds:
            data = {}
            for var in variables:
                # 处理字符串变量
                if var == 'Station':
                    station_data = ds.variables[var][:]
                    if station_data.dtype == 'S1':  # 字符数组
                        data[var] = [''.join(station).strip().decode('utf-8') for station in station_data]
                    else:  # 假设已经是字符串数组
                        data[var] = [str(station).strip() for station in station_data]
                else:
                    data[var] = ds.variables[var][:]
            return data
    except Exception as e:
        print(f"[{get_current_timestamp()}] Error loading {file_path}: {str(e)}")
        return None


def set_brdf_model(s, lucc_value):
    """根据LUCC类型设置BRDF模型"""
    brdf_params = LUCC_TO_BRDF.get(lucc_value, LUCC_TO_BRDF[255])

    if brdf_params["model"] == "Rahman":
        s.ground_reflectance = GroundReflectance.HomogeneousRahman(
            intensity=brdf_params["intensity"],
            asymmetry_factor=brdf_params["asymmetry"],
            structural_parameter=brdf_params["structural"]
        )
    elif brdf_params["model"] == "Walthall":
        s.ground_reflectance = GroundReflectance.HomogeneousWalthall(
            param1=brdf_params["param1"],
            param2=brdf_params["param2"],
            param3=brdf_params["param3"],
            albedo=brdf_params["albedo"]
        )
    else:  # Lambertian
        s.ground_reflectance = GroundReflectance.HomogeneousLambertian(brdf_params["albedo"])

    return s


def process_timepoint(date, time_str, stations_list, mod08_data, lucc_data):
    """处理单个时间点的数据"""
    date_str = date.strftime("%Y%m%d")
    time_dir = time_str[:2]  # 小时部分作为目录名

    # 构建文件路径
    l1_file = os.path.join(PATHS["h8_l1"], date_str, time_dir, f"H8_{date_str}_{time_str}.nc")
    l2arp_file = os.path.join(PATHS["h8_l2arp"], date_str[:4], date_str[4:6], f"H8L2ARP_{date_str}_{time_str}.nc")
    output_file = os.path.join(PATHS["output"], f"SR_{date_str}_{time_str}.nc")

    # 检查输入文件是否存在
    if not os.path.exists(l1_file) or not os.path.exists(l2arp_file):
        return None

    # 加载L1 TOA数据
    l1_data = load_netcdf_data(l1_file, ['Station'] + BAND_NAMES + ['SAZ', 'SAA', 'SOZ', 'SOA'])
    if l1_data is None:
        return None

    # 加载L2ARP数据
    l2arp_data = load_netcdf_data(l2arp_file, ['Station', 'Data_Availability', 'Cloud_Flag', 'AOT'])
    if l2arp_data is None:
        return None

    # 创建站点索引映射
    station_idx_map = {}
    for idx, station in enumerate(l1_data['Station']):
        station_idx_map[station] = idx

    # 初始化结果数组
    num_stations = len(stations_list)
    sr_results = np.full((num_stations, len(BAND_WAVELENGTHS)), np.nan, dtype=np.float32)
    valid_flags = np.zeros(num_stations, dtype=bool)

    # 处理每个站点
    for station_idx, station in enumerate(stations_list):
        # 检查L2ARP数据是否可用
        if station not in station_idx_map:
            continue

        idx = station_idx_map[station]

        # 应用L2ARP云和可用性过滤
        if (l2arp_data['Data_Availability'][idx] != 1 or
                l2arp_data['Cloud_Flag'][idx] != 0):
            continue

        # 获取AOD
        aot = l2arp_data['AOT'][idx]

        # 获取TOA反射率和角度
        toa_reflectances = [l1_data[band][idx] for band in BAND_NAMES]
        saz = l1_data['SAZ'][idx]
        saa = l1_data['SAA'][idx]
        soz = l1_data['SOZ'][idx]
        soa = l1_data['SOA'][idx]

        # 获取水汽和臭氧
        water_vapor, ozone = -1, -1
        if mod08_data is not None and station in mod08_data:
            water_vapor, ozone = mod08_data[station]

        # 获取LUCC类型
        lucc_value = 255  # 默认值
        if lucc_data is not None and station in lucc_data:
            lucc_value = lucc_data[station]

        # 执行6S大气校正+BRDF归一化
        try:
            s = SixS()

            # 设置几何参数
            s.geometry.solar_z = soz
            s.geometry.solar_a = soa
            s.geometry.view_z = saz
            s.geometry.view_a = saa

            # 设置大气参数
            if water_vapor > 0 and ozone > 0:
                s.atmos_profile = AtmosProfile.UserWaterAndOzone(water=water_vapor, ozone=ozone)
            else:
                s.atmos_profile = AtmosProfile.PredefinedType(AtmosProfile.MidlatitudeSummer)

            # 设置气溶胶参数
            if aot > 0:
                s.aot550 = aot * 0.98  # 500nm转换为550nm近似值
            else:
                s.aero_profile = AeroProfile.PredefinedType(AeroProfile.Continental)

            # 设置BRDF模型
            s = set_brdf_model(s, lucc_value)

            # 处理每个波段
            for band_idx, (wavelength, toa_refl) in enumerate(zip(BAND_WAVELENGTHS, toa_reflectances)):
                s.wavelength = Wavelength(wavelength)
                s.atmos_corr = AtmosCorr.AtmosCorrBRDFFromReflectance(reflectance=toa_refl)
                s.run()
                sr_results[station_idx, band_idx] = s.outputs.surface_reflectance

            valid_flags[station_idx] = True
        except Exception as e:
            print(f"[{get_current_timestamp()}] Error processing station {station} at {date_str}_{time_str}: {str(e)}")

    # 保存结果到NetCDF
    try:
        with nc.Dataset(output_file, 'w') as ds:
            # 创建维度
            ds.createDimension('station', num_stations)
            ds.createDimension('band', len(BAND_WAVELENGTHS))

            # 创建变量
            station_var = ds.createVariable('station', str, ('station',))
            station_var[:] = np.array(stations_list, dtype='S20')

            sr_var = ds.createVariable('surface_reflectance', np.float32, ('station', 'band'))
            sr_var.units = '1'
            sr_var.long_name = 'Surface Reflectance after 6S+BRDF correction'
            sr_var[:] = sr_results

            valid_var = ds.createVariable('valid_flag', np.int8, ('station',))
            valid_var.long_name = 'Data validity flag (1=valid, 0=invalid)'
            valid_var[:] = valid_flags.astype(np.int8)

            # 添加全局属性
            ds.date_created = get_current_timestamp()
            ds.source = 'Himawari-8 L1 TOA and L2ARP data processed with Py6S'
            ds.time = time_str
            ds.date = date_str

        return output_file
    except Exception as e:
        print(f"[{get_current_timestamp()}] Error saving {output_file}: {str(e)}")
        return None


def process_date(date, stations_list, mod08_data, lucc_data):
    """处理单个日期的所有时间点"""
    date_str = date.strftime("%Y%m%d")
    print(f"[{get_current_timestamp()}] Processing date: {date_str}")

    # 生成该日期所有时间点 (00:00 到 23:50, 10分钟间隔)
    time_points = [f"{hour:02d}{minute:02d}"
                   for hour in range(24)
                   for minute in range(0, 60, 10)]

    processed_files = []

    for time_str in time_points:
        output_file = process_timepoint(date, time_str, stations_list, mod08_data, lucc_data)
        if output_file:
            processed_files.append(output_file)

    return processed_files


def load_mod08_data(date):
    """加载MOD08数据"""
    date_str = date.strftime("%Y%m%d")
    file_path = os.path.join(PATHS["mod08"], f"poi_mod08_{date_str}.csv")

    if not os.path.exists(file_path):
        return None

    try:
        df = pd.read_csv(file_path)
        return {row['Station']: (row['Water_Vapor'], row['Ozone']) for _, row in df.iterrows()}
    except Exception as e:
        print(f"[{get_current_timestamp()}] Error loading MOD08 data: {str(e)}")
        return None


def load_lucc_data(year):
    """加载LUCC数据"""
    file_path = os.path.join(PATHS["mcd12q1"], f"lucc_{year}.csv")

    if not os.path.exists(file_path):
        return None

    try:
        df = pd.read_csv(file_path)
        return {row['Station']: row['LUCC_value'] for _, row in df.iterrows()}
    except Exception as e:
        print(f"[{get_current_timestamp()}] Error loading LUCC data: {str(e)}")
        return None


def main():
    """主处理函数"""
    start_time = time.time()

    # 创建输出目录
    os.makedirs(PATHS["output"], exist_ok=True)

    # 加载站点信息
    stations_df = pd.read_csv(PATHS["stations"], header=None, names=["Station", "Lon", "Lat"])
    stations_list = stations_df["Station"].tolist()
    num_stations = len(stations_list)
    print(f"[{get_current_timestamp()}] Loaded {num_stations} stations")

    # 生成日期列表
    date_list = []
    current_date = START_DATE
    while current_date <= END_DATE:
        date_list.append(current_date)
        current_date += timedelta(days=1)

    print(f"[{get_current_timestamp()}] Processing {len(date_list)} days from {START_DATE} to {END_DATE}")

    # 多进程处理
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = []

        for date in date_list:
            # 加载该日期所需的数据
            mod08_data = load_mod08_data(date)
            lucc_data = load_lucc_data(date.year)

            futures.append(
                executor.submit(process_date, date, stations_list, mod08_data, lucc_data)
            )

        total_processed = 0
        for future in as_completed(futures):
            try:
                processed_files = future.result()
                total_processed += len(processed_files)
                print(
                    f"[{get_current_timestamp()}] Processed {len(processed_files)} timepoints. Total: {total_processed}")
            except Exception as e:
                print(f"[{get_current_timestamp()}] Processing error: {str(e)}")

    total_time = (time.time() - start_time) / 3600
    print(f"[{get_current_timestamp()}] Processing completed in {total_time:.2f} hours")


if __name__ == "__main__":
    main()