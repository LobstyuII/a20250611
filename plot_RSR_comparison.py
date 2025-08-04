# 需要的改进1：两个波段只在一个比较窄的相关范围内绘制，要不然在400-900nm范围内绘制，会导致在无反射率/反射率极低的情况下绘制一条贴紧x轴的线，不好看
# 改进2：绘制的中心波长部分，标记很难看，请恢复中心波长的垂直线，并且使用箭头标记出他们的值，而非在x轴上，因为他们的中心波段很接近，太挤了不能更好写明谁是谁

import netCDF4 as nc
import matplotlib.pyplot as plt
import numpy as np

# 读取两个NC文件
modis_ds = nc.Dataset(r'D:\H8_data\MODIST_RSRs.nc')
h8_ds = nc.Dataset(r'D:\H8_data\H8_RSRs.nc')

# 提取MODIS数据
modis_wl = modis_ds['wavelength_nm'][:]
modis_red = modis_ds['RSR_Red'][:]
modis_nir = modis_ds['RSR_NIR'][:]

# 提取Himawari-8数据
h8_wl = h8_ds['wavelength_nm'][:]
h8_red = h8_ds['RSR_Red'][:]
h8_nir = h8_ds['RSR_NIR'][:]

# 创建绘图
plt.figure(figsize=(12, 8), dpi=100)

# 绘制红波段响应
plt.plot(modis_wl, modis_red, 'r-', linewidth=2.5, label='MODIS Red (645nm)')
plt.plot(h8_wl, h8_red, 'r--', linewidth=2.5, label='Himawari-8 Red (640nm)')

# 绘制近红外波段响应
plt.plot(modis_wl, modis_nir, 'b-', linewidth=2.5, label='MODIS NIR (859nm)')
plt.plot(h8_wl, h8_nir, 'b--', linewidth=2.5, label='Himawari-8 NIR (860nm)')

# 添加标注和美化
plt.title('Comparison of Spectral Response Functions', fontsize=16, pad=20)
plt.xlabel('Wavelength (nm)', fontsize=14)
plt.ylabel('Relative Spectral Response', fontsize=14)
plt.grid(True, linestyle='--', alpha=0.7)

# 将图例移动到左上角
plt.legend(fontsize=12, loc='upper left')

# 设置坐标轴范围和颜色为黑色
plt.xlim(400, 900)
plt.ylim(-0.05, 1.05)
plt.gca().spines['bottom'].set_color('black')
plt.gca().spines['left'].set_color('black')
plt.gca().spines['top'].set_color('black')
plt.gca().spines['right'].set_color('black')

'''
# 添加波段中心位置的垂直线
plt.axvline(x=645, color='red', linestyle='-', alpha=0.3, linewidth=1.5)
plt.axvline(x=640, color='red', linestyle='--', alpha=0.3, linewidth=1.5)
plt.axvline(x=859, color='blue', linestyle='-', alpha=0.3, linewidth=1.5)
plt.axvline(x=860, color='blue', linestyle='--', alpha=0.3, linewidth=1.5)

# 在x轴上标注中心波长位置
plt.text(645, -0.08, '645', color='red', ha='center', fontsize=10)
plt.text(640, -0.12, '640', color='red', ha='center', fontsize=10)
plt.text(859, -0.08, '859', color='blue', ha='center', fontsize=10)
plt.text(860, -0.12, '860', color='blue', ha='center', fontsize=10)
'''

# 显示图表
plt.tight_layout()
plt.savefig('RSR_comparison.png', dpi=300, bbox_inches='tight')
plt.show()