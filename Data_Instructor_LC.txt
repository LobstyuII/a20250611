MODIS MCD12Q1 土地覆盖数据文件说明
====================================

1. 文件基本信息
   - 文件名: LC_2015_2024.nc
   - 存储路径: D:/H8_data/
   - 时间范围: 2015-2024年 (年度数据)
   - 空间范围: 基于LUTs.nc中的站点位置
   - 文件大小: 约150-200 KB (取决于站点数量)

2. 文件格式
   - 格式类型: NetCDF-4
   - 维度:
        Station: 站点数量 (与LUTs.nc一致)
        time: 10 (2015-2024年)
   - 变量: 5个

3. 数据内容
   | 变量名     | 描述                       | 单位 | 数据类型 | 维度              | 缺失值 |
   |------------|----------------------------|------|----------|-------------------|--------|
   | Station    | 站点名称                   | 无   | 字符串   | Station           | 无     |
   | Lat        | 站点纬度                   | °    | float32  | Station           | 无     |
   | Lon        | 站点经度                   | °    | float32  | Station           | 无     |
   | time       | 时间坐标 (年)              | 年   | int32    | time              | 无     |
   | LC_type1   | IGBP土地覆盖分类           | 类   | int16    | (time, Station)   | -9999  |

4. 土地覆盖分类说明 (LC_type1)
   - 分类方案: 国际地球-生物圈计划 (IGBP) 年度分类
   - 类表:
        | 值  | 说明                        |
        |-----|-----------------------------|
        | 1   | 常绿针叶林                  |
        | 2   | 常绿阔叶林                  |
        | 3   | 落叶针叶林                  |
        | 4   | 落叶阔叶林                  |
        | 5   | 混合森林                    |
        | 6   | 闭合灌木林                  |
        | 7   | 开阔灌木林                  |
        | 8   | 木质稀树草原                |
        | 9   | 热带草原                    |
        | 10  | 草地                        |
        | 11  | 永久性湿地                  |
        | 12  | 农地                        |
        | 13  | 城市和已建成土地            |
        | 14  | 农地/自然植被拼接图         |
        | 15  | 永久性雪和冰                |
        | 16  | 荒漠                        |
        | 17  | 水域                        |
        | 255 | 未分类 (原始数据中的缺失值) |

5. 数据处理说明
   - 数据来源: Google Earth Engine (MODIS/061/MCD12Q1)
   - 时间处理:
        * 每年使用全年的合成产品
        * 时间坐标以"years since 2015-01-01"表示
   - 空间处理:
        * 在500米分辨率下采样站点位置
        * 站点顺序与LUTs.nc保持一致
   - 质量控制:
        * 原始值255 (未分类) 转换为-9999
        * 采样失败的位置填充-9999
   - 坐标系: WGS84 (经纬度)

6. 数据获取信息
   - 卫星: Terra/Aqua
   - 产品: MODIS Land Cover Type Yearly L3 Global 500m (MCD12Q1)
   - 版本: 061
   - 时间跨度: 2001-2024年 (本文件取2015-2024)
   - 原始分辨率: 500米

7. 使用注意事项
   - 需配合LUTs.nc文件中的站点信息使用
   - 缺失值(-9999)表示该站点/年份无有效数据
   - 年度数据代表全年综合土地覆盖状况
   - 分类系统详细说明参考:
        https://lpdaac.usgs.gov/products/mcd12q1v061/

----------------------------------------------------------------

MODIS MCD12Q1 Land Cover Data File Documentation
================================================

1. File Information
   - Filename: LC_2015_2024.nc
   - Path: D:/H8_data/
   - Temporal Coverage: 2015-2024 (Annual data)
   - Spatial Coverage: Station locations from LUTs.nc
   - File Size: ~150-200 KB (depends on station count)

2. File Format
   - Format Type: NetCDF-4
   - Dimensions:
        Station: Number of stations (same as LUTs.nc)
        time: 10 (2015-2024 years)
   - Variables: 5

3. Data Content
   | Variable   | Description                     | Unit | Data Type | Dimensions       | Missing Value |
   |------------|---------------------------------|------|-----------|------------------|---------------|
   | Station    | Station names                   | None | String    | Station          | None          |
   | Lat        | Station latitude                | °    | float32   | Station          | None          |
   | Lon        | Station longitude               | °    | float32   | Station          | None          |
   | time       | Time coordinate (years)         | yr   | int32     | time             | None          |
   | LC_type1   | IGBP Land Cover Classification  | class| int16     | (time, Station)  | -9999         |

4. Land Cover Classification (LC_type1)
   - Scheme: IGBP Annual Classification
   - Class Table:
        | Value | Description                      |
        |-------|----------------------------------|
        | 1     | Evergreen Needleleaf Forests     |
        | 2     | Evergreen Broadleaf Forests     |
        | 3     | Deciduous Needleleaf Forests    |
        | 4     | Deciduous Broadleaf Forests     |
        | 5     | Mixed Forests                   |
        | 6     | Closed Shrublands               |
        | 7     | Open Shrublands                 |
        | 8     | Woody Savannas                  |
        | 9     | Savannas                        |
        | 10    | Grasslands                      |
        | 11    | Permanent Wetlands              |
        | 12    | Croplands                       |
        | 13    | Urban and Built-up Lands        |
        | 14    | Cropland/Natural Vegetation Mosaics|
        | 15    | Permanent Snow and Ice          |
        | 16    | Barren                          |
        | 17    | Water Bodies                    |
        | 255   | Unclassified (raw missing value)|

5. Data Processing
   - Source: Google Earth Engine (MODIS/061/MCD12Q1)
   - Temporal Processing:
        * Uses annual composite product
        * Time in "years since 2015-01-01"
   - Spatial Processing:
        * Sampled at 500m resolution at station locations
        * Station order consistent with LUTs.nc
   - Quality Control:
        * Original value 255 (unclassified) converted to -9999
        * Failed samples filled with -9999
   - Coordinate System: WGS84 (latitude/longitude)

6. Data Source
   - Satellite: Terra/Aqua
   - Product: MODIS Land Cover Type Yearly L3 Global 500m (MCD12Q1)
   - Version: 061
   - Temporal Span: 2001-2024 (this file: 2015-2024)
   - Native Resolution: 500m

7. Usage Notes
   - Use with station information from LUTs.nc
   - Missing values (-9999) indicate no valid data for station/year
   - Annual data represents integrated land cover status
   - Detailed classification system reference:
        https://lpdaac.usgs.gov/products/mcd12q1v061/