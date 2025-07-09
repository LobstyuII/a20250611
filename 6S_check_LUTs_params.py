import os
import netCDF4 as nc
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from scipy import stats
import json

# 配置参数
PATHS = {
    "hourly_toa": "D:/H8_data/Hourly_TOA_Angles/",
    "merra2": "D:/H8_data/MERRA2/",
    "merra2_aot550": "D:/H8_data/MERRA2_AOT550/",
    "lucc": "D:/H8_data/LC_2015_2024.nc",  # 添加LUCC路径
    "output": "D:/H8_Data/Parameter_Analysis/"
}

# 分析范围
START_DATE = datetime(2016, 1, 1)
END_DATE = datetime(2016, 12, 31)
PROCESS_HOURS = list(range(0, 13)) + list(range(21, 24))

# 要分析的参数 - 添加LUCC
PARAMETERS = {
    "solar_zenith": {"values": [], "unit": "degrees", "physical_min": 0, "physical_max": 85},
    "view_zenith": {"values": [], "unit": "degrees", "physical_min": 0, "physical_max": 70},
    "relative_azimuth": {"values": [], "unit": "degrees", "physical_min": 0, "physical_max": 180},
    "aot550": {"values": [], "unit": "dimensionless", "physical_min": 0, "physical_max": 5},
    "water": {"values": [], "unit": "g/cm²", "physical_min": 0, "physical_max": 10},
    "ozone": {"values": [], "unit": "cm-atm", "physical_min": 0, "physical_max": 1},
    "toa_reflectance_band03": {"values": [], "unit": "dimensionless", "physical_min": 0, "physical_max": 1.2},
    "toa_reflectance_band04": {"values": [], "unit": "dimensionless", "physical_min": 0, "physical_max": 1.2},
    "lucc": {"values": [], "unit": "category", "physical_min": 1, "physical_max": 255}  # 添加LUCC参数
}

# 初始化目录
os.makedirs(PATHS["output"], exist_ok=True)


# 加载LUCC数据
def load_lucc():
    """加载LUCC数据并构建站点到LUCC的映射"""
    try:
        with nc.Dataset(PATHS["lucc"]) as ds:
            stations = [str(s).strip() for s in ds.variables['Station'][:]]
            lucc = ds.variables['LC_type1'][1, :]  # 使用2016年数据（索引1）
            if isinstance(lucc, np.ma.MaskedArray):
                lucc = lucc.filled(255)
            lucc_dict = dict(zip(stations, lucc))
            print(f"加载LUCC数据，共{len(lucc_dict)}个站点")
            return lucc_dict
    except Exception as e:
        print(f"加载LUCC数据失败: {str(e)}")
        return {}


def load_netcdf(file_path, variables):
    """加载NetCDF数据"""
    if not os.path.exists(file_path):
        return None

    try:
        with nc.Dataset(file_path) as ds:
            data = {}
            for var in variables:
                if var not in ds.variables:
                    continue

                var_data = ds.variables[var][:]

                # 处理站点名称
                if var == 'Station':
                    if var_data.dtype.kind in ['S', 'U']:
                        # 统一处理站点名称
                        if var_data.dtype.kind == 'S':
                            var_data = [s.decode('utf-8').strip() for s in var_data]
                        else:
                            var_data = [s.strip() for s in var_data]
                    else:
                        var_data = [str(s).strip() for s in var_data]
                    data[var] = var_data
                else:
                    if isinstance(var_data, np.ma.MaskedArray):
                        var_data = var_data.filled(np.nan)

                    # 处理MERRA2的缺失值
                    if var in ['AOT550', 'TO3', 'TQV']:
                        var_data = np.where(var_data == -9999.0, np.nan, var_data)

                    data[var] = var_data
            return data
    except Exception as e:
        print(f"加载{file_path}失败: {str(e)}")
        return None


def convert_merra2_units(to3, tqv):
    """转换MERRA2单位"""
    if np.isnan(to3) or np.isnan(tqv):
        return np.nan, np.nan
    return to3 * 0.001, tqv * 0.1  # Dobson->cm-atm, kg/m²->g/cm²


def calculate_relative_azimuth(saa, soa):
    """计算相对方位角"""
    rel_az = abs(saa - soa)
    rel_az = min(rel_az, 360 - rel_az)
    return min(rel_az, 180)  # 确保在0-180度之间


def analyze_parameters(date, hour, lucc_dict):
    """分析单小时数据的参数分布"""
    date_str = date.strftime("%Y%m%d")
    hour_str = f"{hour * 100:04d}"
    time_key = f"{date_str}_{hour_str}"

    # 文件路径
    paths = {
        "toa": os.path.join(PATHS["hourly_toa"], date_str[:4], date_str[4:6], f"H8_hourly_TOA_angles_{time_key}.nc"),
        "merra": os.path.join(PATHS["merra2"], date_str[:4], date_str[4:6], f"MERRA2_{time_key}_TO3_TQV.nc"),
        "aot550": os.path.join(PATHS["merra2_aot550"], date_str[:4], date_str[4:6], f"MERRA2_{time_key}_AOT550.nc")
    }

    # 检查文件是否存在
    if not all(os.path.exists(p) for p in paths.values()):
        return

    # 加载数据 - 添加'Station'变量
    hourly = load_netcdf(paths["toa"], ['Station', 'SAZ', 'SAA', 'SOZ', 'SOA', 'Albedo_03', 'Albedo_04'])
    merra2 = load_netcdf(paths["merra"], ['Station', 'TO3', 'TQV'])
    aot550_data = load_netcdf(paths["aot550"], ['Station', 'AOT550'])

    if None in [hourly, merra2, aot550_data]:
        return

    # 获取站点列表
    stations = hourly.get('Station', [])
    n = len(stations)

    for i in range(n):
        station = stations[i] if i < len(stations) else None

        # 获取LUCC值
        lucc_value = lucc_dict.get(station, 255) if station else 255
        PARAMETERS["lucc"]["values"].append(lucc_value)

        # 获取角度
        soz = hourly.get('SOZ', [np.nan])[i]
        saz = hourly.get('SAZ', [np.nan])[i]
        saa = hourly.get('SAA', [np.nan])[i]
        soa = hourly.get('SOA', [np.nan])[i]

        # 计算相对方位角
        rel_az = calculate_relative_azimuth(saa, soa) if not np.isnan(saa) and not np.isnan(soa) else np.nan

        # 获取大气参数
        to3 = merra2.get('TO3', [np.nan])[i]
        tqv = merra2.get('TQV', [np.nan])[i]
        ozone, water = convert_merra2_units(to3, tqv)
        aot550 = aot550_data.get('AOT550', [np.nan])[i]

        # 获取TOA反射率
        albedo03 = hourly.get('Albedo_03', [np.nan])[i]
        albedo04 = hourly.get('Albedo_04', [np.nan])[i]

        # 计算TOA反射率（考虑太阳天顶角）
        cos_soz = np.cos(np.radians(soz)) if not np.isnan(soz) else np.nan
        toa03 = albedo03 / max(cos_soz, 0.01) if not np.isnan(albedo03) and not np.isnan(cos_soz) else np.nan
        toa04 = albedo04 / max(cos_soz, 0.01) if not np.isnan(albedo04) and not np.isnan(cos_soz) else np.nan

        # 收集有效参数值
        if 0 <= soz <= 85:
            PARAMETERS["solar_zenith"]["values"].append(soz)

        if 0 <= saz <= 70:
            PARAMETERS["view_zenith"]["values"].append(saz)

        if 0 <= rel_az <= 180:
            PARAMETERS["relative_azimuth"]["values"].append(rel_az)

        if 0 <= aot550 <= 5:
            PARAMETERS["aot550"]["values"].append(aot550)

        if 0 <= water <= 10:
            PARAMETERS["water"]["values"].append(water)

        if 0 <= ozone <= 1:
            PARAMETERS["ozone"]["values"].append(ozone)

        if 0 <= toa03 <= 1.2:
            PARAMETERS["toa_reflectance_band03"]["values"].append(toa03)

        if 0 <= toa04 <= 1.2:
            PARAMETERS["toa_reflectance_band04"]["values"].append(toa04)


def calculate_statistics():
    """计算每个参数的统计特征"""
    results = {}

    for param, data in PARAMETERS.items():
        values = np.array(data["values"])

        if len(values) == 0:
            continue

        # LUCC的特殊处理（分类变量）
        if param == "lucc":
            # 计算类别频率
            unique, counts = np.unique(values, return_counts=True)
            total = len(values)
            frequencies = counts / total

            # 获取所有出现的类别
            present_categories = unique.tolist()

            results[param] = {
                "count": total,
                "categories": [int(cat) for cat in present_categories],
                "frequencies": frequencies.tolist(),
                "unit": data["unit"]
            }
        else:
            # 基本统计（连续变量）
            mean = np.nanmean(values)
            std = np.nanstd(values)
            min_val = np.nanmin(values)
            max_val = np.nanmax(values)

            # 95%置信区间
            lower_bound = np.nanpercentile(values, 2.5)
            upper_bound = np.nanpercentile(values, 97.5)

            # 物理边界
            physical_min = data["physical_min"]
            physical_max = data["physical_max"]

            # 建议边界 - 取95%置信区间和物理边界的交集
            recommended_min = max(lower_bound, physical_min)
            recommended_max = min(upper_bound, physical_max)

            results[param] = {
                "count": len(values),
                "mean": float(mean),
                "std": float(std),
                "min": float(min_val),
                "max": float(max_val),
                "95_lower": float(lower_bound),
                "95_upper": float(upper_bound),
                "physical_min": physical_min,
                "physical_max": physical_max,
                "recommended_min": float(recommended_min),
                "recommended_max": float(recommended_max),
                "unit": data["unit"]
            }

    return results


def plot_distributions(results):
    """绘制参数分布图"""
    output_dir = os.path.join(PATHS["output"], "plots")
    os.makedirs(output_dir, exist_ok=True)

    for param, stats in results.items():
        values = np.array(PARAMETERS[param]["values"])

        if len(values) == 0:
            continue

        # LUCC的特殊处理（绘制类别频率图）
        if param == "lucc":
            plt.figure(figsize=(12, 6))
            categories = stats["categories"]
            freqs = stats["frequencies"]

            # 创建柱状图
            plt.bar(range(len(categories)), freqs, tick_label=categories)
            plt.title(f"LUCC Category Distribution (n={stats['count']})")
            plt.xlabel("LUCC Category")
            plt.ylabel("Frequency")
            plt.grid(axis='y', alpha=0.3)
            plt.xticks(rotation=45)

            # 保存图像
            plt.savefig(os.path.join(output_dir, f"{param}_distribution.png"), bbox_inches='tight')
            plt.close()
        else:
            plt.figure(figsize=(10, 6))

            # 直方图
            plt.hist(values, bins=100, alpha=0.7, density=True, label="Distribution")

            # KDE曲线
            try:
                kde = stats.gaussian_kde(values)
                x = np.linspace(min(values), max(values), 1000)
                plt.plot(x, kde(x), 'r-', linewidth=2, label="KDE")
            except:
                pass

            # 标注关键值
            plt.axvline(stats["95_lower"], color='g', linestyle='--', label="95% Lower")
            plt.axvline(stats["95_upper"], color='g', linestyle='--', label="95% Upper")
            plt.axvline(stats["recommended_min"], color='r', linestyle='-', label="Rec Min")
            plt.axvline(stats["recommended_max"], color='r', linestyle='-', label="Rec Max")

            plt.title(f"{param} Distribution (n={stats['count']:,})")
            plt.xlabel(f"{param} ({stats['unit']})")
            plt.ylabel("Density")
            plt.legend()
            plt.grid(True, alpha=0.3)

            # 保存图像
            plt.savefig(os.path.join(output_dir, f"{param}_distribution.png"), bbox_inches='tight')
            plt.close()


def main():
    """主分析函数"""
    print("开始分析2016年参数分布...")

    # 加载LUCC数据
    lucc_dict = load_lucc()
    if not lucc_dict:
        print("警告: 无法加载LUCC数据，将使用默认值255")
        lucc_dict = {}

    # 生成日期列表
    dates = []
    current = START_DATE
    while current <= END_DATE:
        dates.append(current)
        current += timedelta(days=1)

    # 处理所有日期和小时
    total = len(dates) * len(PROCESS_HOURS)
    processed = 0

    for date in dates:
        for hour in PROCESS_HOURS:
            analyze_parameters(date, hour, lucc_dict)
            processed += 1

            # 每处理10个文件打印一次进度
            if processed % 10 == 0:
                print(f"进度: {processed}/{total} ({processed / total * 100:.1f}%)")

    # 计算统计结果
    results = calculate_statistics()

    # 保存结果
    with open(os.path.join(PATHS["output"], "parameter_statistics.json"), "w") as f:
        json.dump(results, f, indent=4)

    # 生成分布图
    plot_distributions(results)

    # 打印建议的LUT边界
    print("\n参数边界建议:")
    print("=" * 60)
    print("{:<25} {:<15} {:<15} {:<15}".format("Parameter", "Recommended Min", "Recommended Max", "Unit"))
    print("-" * 60)
    for param, stats in results.items():
        if param == "lucc":
            # LUCC的特殊输出（类别列表）
            print("{:<25} {:<15} {:<15} {:<15}".format(
                param,
                f"Categories: {len(stats['categories'])}",
                f"Min: {min(stats['categories'])}",
                stats["unit"]))
        else:
            print("{:<25} {:<15.4f} {:<15.4f} {:<15}".format(
                param, stats["recommended_min"], stats["recommended_max"], stats["unit"]))
    print("=" * 60)

    # 单独打印LUCC类别频率
    if "lucc" in results:
        print("\nLUCC类别频率:")
        print("Category\tFrequency")
        for cat, freq in zip(results["lucc"]["categories"], results["lucc"]["frequencies"]):
            print(f"{cat}\t\t{freq:.4f}")

    print(f"\n分析完成! 结果保存至: {PATHS['output']}")


if __name__ == "__main__":
    main()