import xarray as xr
import matplotlib.pyplot as plt
import numpy as np
import logging
import os
from pathlib import Path
import matplotlib.dates as mdates

# 配置科研级字体
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Times New Roman']
plt.rcParams['mathtext.fontset'] = 'stix'
plt.rcParams['axes.edgecolor'] = 'black'
plt.rcParams['axes.linewidth'] = 1.0

# 配置路径
INPUT_DIR = r"D:\H8_data\NDVI_Decomposition"  # STL分解结果目录


def plot_station_decomposition(nc_file, output_dir):
    """绘制单个站点的STL分解图"""
    try:
        station_id = nc_file.stem.split('_')[-1]
        logging.info(f"绘制站点 {station_id} 的STL分解图")

        # 打开NetCDF文件
        ds = xr.open_dataset(nc_file)

        # 创建图形
        fig, axs = plt.subplots(5, 1, figsize=(12, 15), sharex=True)
        fig.suptitle(f'STL Decomposition - Station {station_id}',
                     fontsize=16, fontname='Times New Roman', y=0.95)

        # 分量列表
        components = {
            'original': ds['NDVI_original'],
            'trend': ds['NDVI_trend'],
            'seasonal': ds['NDVI_seasonal'],
            'residual': ds['NDVI_residual'],
            'status': ds['status']
        }

        # 绘制各分量
        titles = ['Original NDVI', 'Trend Component', 'Seasonal Component',
                  'Residual Component', 'Data Status']

        for i, (key, title) in enumerate(zip(components.keys(), titles)):
            ax = axs[i]
            data = components[key]

            # 特殊处理残差分量
            if key == 'residual':
                # 只绘制有效点 (status == 0)
                valid_mask = (components['status'] == 0)
                valid_times = data.time.values[valid_mask]
                valid_values = data.values[valid_mask]

                if len(valid_times) > 0:
                    ax.plot(valid_times, valid_values, 'b.', markersize=1, alpha=0.7)
                ax.axhline(0, color='gray', linestyle='--', alpha=0.5)

            # 特殊处理状态分量
            elif key == 'status':
                # 将状态转换为颜色：有效点为绿色，夜间点为橙色
                colors = np.where(data.values == 0, 'green', 'orange')

                # 绘制状态点（在时间轴上每个点画一个竖线）
                for j, t in enumerate(data.time.values):
                    ax.axvline(x=t, color=colors[j], alpha=0.1, linewidth=0.5)

                # 设置图例
                from matplotlib.lines import Line2D
                custom_lines = [
                    Line2D([0], [0], color='green', lw=2),
                    Line2D([0], [0], color='orange', lw=2)
                ]
                ax.legend(custom_lines, ['Valid', 'Night/Interp'],
                          loc='upper right', frameon=False)

            else:
                # 绘制其他分量
                ax.plot(data.time, data, 'b-', linewidth=0.8)

            # 设置标签和样式
            ax.set_ylabel(title, fontsize=10)
            ax.grid(True, linestyle='--', alpha=0.3)

            # 科研风格优化
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['bottom'].set_linewidth(0.5)
            ax.spines['left'].set_linewidth(0.5)

            # 设置最后一张图的x轴格式
            if i == len(axs) - 1:
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
                ax.tick_params(axis='x', rotation=45)

        # 调整布局
        plt.tight_layout(rect=[0, 0, 1, 0.96])

        # 保存图形
        plt.savefig(output_dir / f"STL_plot_{station_id}.png", dpi=150, bbox_inches='tight')
        plt.close(fig)
        ds.close()

        return True
    except Exception as e:
        print(f"绘制站点 {station_id} 出错: {str(e)}")
        return False


def main():
    """主函数：批量绘制所有站点STL分解图"""
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger()

    input_dir = Path(INPUT_DIR)
    output_dir = input_dir / "STL_Plots"
    output_dir.mkdir(exist_ok=True)

    # 获取所有STL分解文件
    nc_files = list(input_dir.glob("**/STL_decomposition_*.nc"))

    if not nc_files:
        logger.error(f"在目录 {input_dir} 中未找到任何STL分解文件")
        return

    logger.info(f"找到 {len(nc_files)} 个STL分解文件")

    # 绘制所有站点
    processed = 0
    for nc_file in nc_files:
        if plot_station_decomposition(nc_file, output_dir):
            processed += 1
            logger.info(f"成功绘制 {nc_file.stem}")

    logger.info(f"完成! 成功绘制 {processed}/{len(nc_files)} 个站点")


if __name__ == "__main__":
    main()