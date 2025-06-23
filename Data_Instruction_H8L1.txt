H8卫星数据文件说明
====================

1. 文件命名规则
   - 格式: H8_YYYYMMDD_HHMM.nc
     示例: H8_20150801_0250.nc
   - 说明:
     * YYYY: 年份 (4位数字)
     * MM: 月份 (2位数字)
     * DD: 日期 (2位数字)
     * HH: 小时 (UTC时间，2位数字)
     * MM: 分钟 (2位数字)

2. 文件格式
   - 格式类型: NetCDF-4
   - 维度: 1 (站点维度)
   - 变量: 11个
   - 文件大小: 约200-300 KB

3. 数据内容
   | 变量名       | 描述                         | 单位 | 数据类型 | 维度         |
   |--------------|------------------------------|------|----------|--------------|
   | Station      | 站点名称                     | 无   | 字符串   | Station(2014)|
   | Albedo_01-06 | 波段1-6地表反照率(经校正)    | 1    | float32  | Station(2014)|
   | SAZ          | 卫星天顶角                   | °    | float32  | Station(2014)|
   | SAA          | 卫星方位角                   | °    | float32  | Station(2014)|
   | SOZ          | 太阳天顶角                   | °    | float32  | Station(2014)|
   | SOA          | 太阳方位角                   | °    | float32  | Station(2014)|

4. 数据处理说明
   - 反照率校正: 所有值已根据太阳天顶角(SOZ)校正
     校正公式: 反照率校正值 = 原始值 / cos(SOZ)
     当cos(SOZ) ≤ 0.01时，使用0.01作为分母
   - 数据质量:
     * 有效值范围: 0.0-1.0 (反照率)
     * 缺失值: NaN
     * 典型有效值比例: >99%
   - 时间表示:
     * 全局属性: time = "0250" (表示02:50 UTC)
     * 完整时间戳: YYYY-MM-DD HH:MM UTC (如2015-08-01 02:50 UTC)

5. 数据来源
   - 卫星: 日本气象厅向日葵8号(Himawari-8)
   - 产品: L1级全圆盘数据
   - 分辨率: 约5km (0.05°)
   - 获取方式: 日本宇宙航空研究开发机构(JAXA)FTP服务器
     ftp://ftp.ptree.jaxa.jp/jma/netcdf/

6. 使用注意事项
   - 文件包含2014个特定站点的数据
   - 每个文件代表单个时间点(10分钟间隔)
   - 月度数据整合后存储在H8_monthly_YYYYMM.nc中
   - 数据通过自动化Python脚本处理，含完整日志记录

----------------------------------------------------------------

H8 Satellite Data File Documentation
====================================

1. File Naming Convention
   - Format: H8_YYYYMMDD_HHMM.nc
     Example: H8_20150801_0250.nc
   - Description:
     * YYYY: Year (4-digit)
     * MM: Month (2-digit)
     * DD: Day (2-digit)
     * HH: Hour (UTC, 2-digit)
     * MM: Minute (2-digit)

2. File Format
   - Format Type: NetCDF-4
   - Dimensions: 1 (Station dimension)
   - Variables: 11
   - File Size: ~200-300 KB

3. Data Content
   | Variable      | Description                     | Unit | Data Type | Dimension     |
   |---------------|---------------------------------|------|-----------|---------------|
   | Station       | Station names                   | None | String    | Station(2014) |
   | Albedo_01-06  | Band 1-6 Albedo (corrected)     | 1    | float32   | Station(2014) |
   | SAZ           | Satellite Zenith Angle          | °    | float32   | Station(2014) |
   | SAA           | Satellite Azimuth Angle         | °    | float32   | Station(2014) |
   | SOZ           | Solar Zenith Angle              | °    | float32   | Station(2014) |
   | SOA           | Solar Azimuth Angle             | °    | float32   | Station(2014) |

4. Data Processing Notes
   - Albedo Correction: All values corrected for solar zenith angle (SOZ)
     Formula: Corrected Albedo = Raw Value / cos(SOZ)
     When cos(SOZ) ≤ 0.01, use 0.01 as denominator
   - Data Quality:
     * Valid Range: 0.0-1.0 (Albedo)
     * Missing Values: NaN
     * Typical Valid Data Ratio: >99%
   - Time Representation:
     * Global Attribute: time = "0250" (02:50 UTC)
     * Full Timestamp: YYYY-MM-DD HH:MM UTC (e.g., 2015-08-01 02:50 UTC)

5. Data Source
   - Satellite: JMA Himawari-8
   - Product: L1 Full Disk Data
   - Resolution: ~5km (0.05°)
   - Access: JAXA P-Tree FTP Server
     ftp://ftp.ptree.jaxa.jp/jma/netcdf/

6. Usage Notes
   - Contains data for 2014 specific stations
   - Each file represents a single 10-minute timepoint
   - Monthly data integrated in H8_monthly_YYYYMM.nc files
   - Processed by automated Python scripts with full logging