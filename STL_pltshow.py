# 看MSTL后的数据图像
# python STL_pltshow.py D:/H8_Data/Decomposition/Albedo_01/decomposed_H8_monthly_201508.nc

import xarray as xr
import matplotlib.pyplot as plt
import numpy as np
import sys
import os


def main():
    if len(sys.argv) < 2:
        print("Usage: python STL_pltshow.py <path_to_nc_file>")
        sys.exit(1)

    nc_file = sys.argv[1]
    # nc_file = "D:\\H8_Data\\Decomposition\\Albedo_01\\decomposed_H8_monthly_201507.nc"

    if not os.path.exists(nc_file):
        print(f"Error: File not found - {nc_file}")
        sys.exit(1)

    try:
        # 打开NetCDF文件
        ds = xr.open_dataset(nc_file)

        # 确定基础变量名（去除后缀）
        base_var = None
        for var in ds.data_vars:
            if var.endswith('_trend'):
                base_var = var.replace('_trend', '')
                break

        if base_var is None:
            print("Error: Could not determine base variable name from the dataset")
            sys.exit(1)

        # 设置分量名称
        components = {
            'original': f"{base_var} (Original)",
            'trend': f"{base_var}_trend",
            'yearly': f"{base_var}_yearly",
            'diurnal': f"{base_var}_diurnal",
            'err': f"{base_var}_err"
        }

        # 获取所有站点
        stations = ds['Station'].values

        # 循环处理每个站点
        for station in stations:
            print(f"Processing station: {station}")

            # 创建图形和子图
            fig, axs = plt.subplots(5, 1, figsize=(12, 15), sharex=True)
            plt.suptitle(f'STL Decomposition - Station {station}', fontsize=16)

            # 获取该站点的数据
            station_data = ds.sel(Station=station)

            # 计算原始数据（各分量之和）
            original = (station_data[components['trend']] +
                        station_data[components['yearly']] +
                        station_data[components['diurnal']] +
                        station_data[components['err']])

            # 绘制各分量曲线
            for i, (key, label) in enumerate(components.items()):
                ax = axs[i]

                if key == 'original':
                    data = original
                else:
                    data = station_data[label]

                # 绘制曲线
                ax.plot(data['time'], data, 'b-', linewidth=1.5)

                # 设置标签和网格
                ax.set_ylabel(label, fontsize=12, rotation=0, labelpad=40, ha='right')
                ax.grid(True, linestyle='--', alpha=0.7)

                # 调整y轴标签位置
                ax.yaxis.set_label_coords(-0.05, 0.5)

            # 设置公共x轴标签
            axs[-1].set_xlabel('Time', fontsize=12)

            # 调整布局
            plt.tight_layout(rect=[0, 0, 1, 0.96])  # 为总标题留出空间

            # 显示图形
            plt.show()

            # 关闭数据集释放资源
            ds.close()

    except Exception as e:
        print(f"Error processing file: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()