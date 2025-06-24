import os
import time
import pandas as pd
import netCDF4 as nc
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
from Py6S import *

# 配置路径
PATHS = {
    "h8_l1": "D:/H8_data/h8l1/",
    "h8_l2arp": "D:/H8_data/h8l2arp/",
    "merra2": "D:/H8_data/MERRA2interp/",
    "lucc": "D:/H8_data/LC_2015_2024.nc",
    "output": "D:/H8_Data/H8SR/",
    "stations": "Air_stations_lon_lat.csv"
}

# 波段参数
BAND_WAVELENGTHS = [0.47, 0.51, 0.64, 0.86, 1.6, 2.3]
BAND_NAMES = [f"Albedo_0{i + 1}" for i in range(1, 7)]
SR_BAND_NAMES = [f"SR_0{i + 1}" for i in range(1, 7)]
ANGLE_NAMES = ['SAZ', 'SAA', 'SOZ', 'SOA']

# 日期范围
START_DATE = datetime(2015, 7, 11)
END_DATE = datetime(2021, 12, 31)

# LUCC到BRDF参数的映射
LUCC_TO_BRDF = {
    1: {"model": "Rahman", "intensity": 0.3, "asymmetry": 0.1, "structural": 0.5},
    2: {"model": "Rahman", "intensity": 0.35, "asymmetry": 0.12, "structural": 0.55},
    3: {"model": "Rahman", "intensity": 0.25, "asymmetry": 0.08, "structural": 0.45},
    4: {"model": "Rahman", "intensity": 0.3, "asymmetry": 0.1, "structural": 0.5},
    5: {"model": "Rahman", "intensity": 0.2, "asymmetry": 0.05, "structural": 0.4},
    6: {"model": "Rahman", "intensity": 0.4, "asymmetry": 0.15, "structural": 0.6},
    7: {"model": "Rahman", "intensity": 0.35, "asymmetry": 0.12, "structural": 0.55},
    8: {"model": "Walthall", "param1": 0.5, "param2": 0.2, "param3": 0.1, "albedo": 0.25},
    9: {"model": "Walthall", "param1": 0.4, "param2": 0.15, "param3": 0.05, "albedo": 0.3},
    10: {"model": "Lambertian", "albedo": 0.35},
    11: {"model": "Lambertian", "albedo": 0.1},
    12: {"model": "Lambertian", "albedo": 0.4},
    13: {"model": "Walthall", "param1": 0.6, "param2": 0.25, "param3": 0.15, "albedo": 0.35},
    14: {"model": "Lambertian", "albedo": 0.7},
    15: {"model": "Lambertian", "albedo": 0.05},
    16: {"model": "Lambertian", "albedo": 0.02},
    17: {"model": "Lambertian", "albedo": 0.02},
    255: {"model": "Lambertian", "albedo": 0.2}
}


def get_current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_netcdf_data(file_path, variables):
    """加载NetCDF文件数据"""
    if not os.path.exists(file_path):
        return None

    try:
        with nc.Dataset(file_path) as ds:
            data = {}
            for var in variables:
                if var == 'Station':
                    station_data = ds.variables[var][:]
                    if station_data.dtype == 'S1':
                        data[var] = [''.join(station).strip().decode('utf-8') for station in station_data]
                    else:
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
    else:
        s.ground_reflectance = GroundReflectance.HomogeneousLambertian(brdf_params["albedo"])
    return s


def calculate_general_availability(l2arp_data, idx):
    """计算综合可用性标志"""
    if (l2arp_data['Data_Availability'][idx] != 1 or
            l2arp_data['Cloud_Flag'][idx] != 0 or
            l2arp_data['Land_Water_Flag'][idx] == 0):
        return 1  # 不可用
    return 0  # 可用


def process_timepoint(date, time_str, stations_list, lucc_dict, merra2_data):
    date_str = date.strftime("%Y%m%d")
    time_dir = time_str[:2]

    # 构建文件路径
    l1_file = os.path.join(PATHS["h8_l1"], date_str, time_dir, f"H8_{date_str}_{time_str}.nc")
    l2arp_file = os.path.join(PATHS["h8_l2arp"], date_str[:4], date_str[4:6], f"H8L2ARP_{date_str}_{time_str}.nc")
    merra2_file = os.path.join(PATHS["merra2"], f"MERRA2_{date_str}_{time_str}.nc")
    output_file = os.path.join(PATHS["output"], f"SR_{date_str}_{time_str}.nc")

    # 检查输入文件
    missing_files = []
    if not os.path.exists(l1_file): missing_files.append(l1_file)
    if not os.path.exists(l2arp_file): missing_files.append(l2arp_file)
    if not os.path.exists(merra2_file): missing_files.append(merra2_file)

    if missing_files:
        print(f"[{get_current_timestamp()}] Missing files for {date_str}_{time_str}: {', '.join(missing_files)}")
        return None

    # 加载数据
    l1_data = load_netcdf_data(l1_file, ['Station'] + BAND_NAMES + ANGLE_NAMES)
    l2arp_data = load_netcdf_data(l2arp_file, ['Station', 'Data_Availability', 'Cloud_Flag', 'Land_Water_Flag', 'AOT'])
    merra2_data = load_netcdf_data(merra2_file, ['Station', 'TO3', 'TQV'])

    if None in [l1_data, l2arp_data, merra2_data]:
        return None

    # 创建站点索引映射
    station_idx_map = {}
    for idx, station in enumerate(l1_data['Station']):
        station_idx_map[station] = idx

    # 初始化结果数组
    num_stations = len(stations_list)
    sr_results = np.full((num_stations, len(BAND_WAVELENGTHS)), np.nan, dtype=np.float32)
    gen_avail = np.full(num_stations, -1, dtype=np.int8)
    valid_flags = np.zeros(num_stations, dtype=np.int8)

    # 处理每个站点
    for station_idx, station in enumerate(stations_list):
        if station not in station_idx_map:
            continue

        idx = station_idx_map[station]

        # 计算综合可用性
        gen_avail[station_idx] = calculate_general_availability(l2arp_data, idx)

        if gen_avail[station_idx] == 1:
            continue  # 不可用数据，跳过处理

        # 获取大气参数
        aot = l2arp_data['AOT'][idx]
        to3 = merra2_data['TO3'][idx]
        tqv = merra2_data['TQV'][idx]

        # 获取TOA反射率和角度
        toa_reflectances = [l1_data[band][idx] for band in BAND_NAMES]
        saz = l1_data['SAZ'][idx]
        saa = l1_data['SAA'][idx]
        soz = l1_data['SOZ'][idx]
        soa = l1_data['SOA'][idx]

        # 获取LUCC类型
        lucc_value = lucc_dict.get(station, 255)

        # 执行6S大气校正+BRDF归一化
        try:
            s = SixS()

            # 设置几何参数
            s.geometry.solar_z = soz
            s.geometry.solar_a = soa
            s.geometry.view_z = saz
            s.geometry.view_a = saa

            # 设置大气参数
            s.atmos_profile = AtmosProfile.UserWaterAndOzone(water=tqv, ozone=to3)

            # 设置气溶胶参数
            s.aot550 = aot * 0.98  # 500nm转换为550nm近似值

            # 设置BRDF模型
            s = set_brdf_model(s, lucc_value)

            # 处理每个波段
            for band_idx, (wavelength, toa_refl) in enumerate(zip(BAND_WAVELENGTHS, toa_reflectances)):
                s.wavelength = Wavelength(wavelength)
                s.atmos_corr = AtmosCorr.AtmosCorrBRDFFromReflectance(reflectance=toa_refl)
                s.run()
                sr_results[station_idx, band_idx] = s.outputs.surface_reflectance

            valid_flags[station_idx] = 1
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

            gen_avail_var = ds.createVariable('General_availability', np.int8, ('station',))
            gen_avail_var.long_name = 'Data availability flag (0=clear land available, 1=other)'
            gen_avail_var[:] = gen_avail

            sr_var = ds.createVariable('surface_reflectance', np.float32, ('station', 'band'))
            sr_var.units = '1'
            sr_var.long_name = 'Surface Reflectance after 6S+BRDF correction'
            sr_var[:] = sr_results

            valid_var = ds.createVariable('valid_flag', np.int8, ('station',))
            valid_var.long_name = 'Processing validity flag (1=success, 0=fail)'
            valid_var[:] = valid_flags

            # 添加全局属性
            ds.date_created = get_current_timestamp()
            ds.title = 'Himawari-8 Surface Reflectance Product'
            ds.source = 'Himawari-8 L1 TOA, L2ARP, MERRA-2, and MCD12Q1 data'
            ds.author = 'Atmospheric Correction Processor v2.0'
            ds.time = time_str
            ds.date = date_str

        print(f"[{get_current_timestamp()}] Generated SR product: {output_file}")
        return output_file
    except Exception as e:
        print(f"[{get_current_timestamp()}] Error saving {output_file}: {str(e)}")
        return None


def load_lucc_data():
    """加载LUCC数据到内存"""
    lucc_file = PATHS["lucc"]
    if not os.path.exists(lucc_file):
        print(f"[{get_current_timestamp()}] LUCC file not found: {lucc_file}")
        return None

    try:
        with nc.Dataset(lucc_file) as ds:
            stations = [''.join(s).strip() for s in ds.variables['Station'][:]]
            # 使用最新年份的数据
            year_idx = -1  # 最后一个时间索引（最新年份）
            lucc_values = ds.variables['LC_type1'][year_idx, :]
            return dict(zip(stations, lucc_values))
    except Exception as e:
        print(f"[{get_current_timestamp()}] Error loading LUCC data: {str(e)}")
        return None


def process_date(date, stations_list, lucc_dict):
    date_str = date.strftime("%Y%m%d")
    print(f"[{get_current_timestamp()}] Processing date: {date_str}")

    # 生成该日期所有时间点
    time_points = [f"{hour:02d}{minute:02d}"
                   for hour in range(24)
                   for minute in range(0, 60, 10)]

    processed_files = []
    for time_str in time_points:
        merra2_data = None  # 每个时间点单独加载MERRA2数据
        output_file = process_timepoint(date, time_str, stations_list, lucc_dict, merra2_data)
        if output_file:
            processed_files.append(output_file)

    return processed_files


def main():
    start_time = time.time()

    # 创建输出目录
    os.makedirs(PATHS["output"], exist_ok=True)

    # 加载站点信息
    stations_df = pd.read_csv(PATHS["stations"], header=None, names=["Station", "Lon", "Lat"])
    stations_list = stations_df["Station"].tolist()
    num_stations = len(stations_list)
    print(f"[{get_current_timestamp()}] Loaded {num_stations} stations")

    # 加载LUCC数据到内存
    lucc_dict = load_lucc_data()
    if lucc_dict is None:
        print(f"[{get_current_timestamp()}] Failed to load LUCC data. Exiting.")
        return

    # 生成日期列表
    date_list = []
    current_date = START_DATE
    while current_date <= END_DATE:
        date_list.append(current_date)
        current_date += timedelta(days=1)

    print(f"[{get_current_timestamp()}] Processing {len(date_list)} days from {START_DATE} to {END_DATE}")

    # 多进程处理
    with ProcessPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(process_date, date, stations_list, lucc_dict) for date in date_list]

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