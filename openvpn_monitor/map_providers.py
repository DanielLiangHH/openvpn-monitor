#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright 2011 VPAC <http://www.vpac.org>
# Copyright 2012-2024 Marcus Furlong <furlongm@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 only.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>

"""地图底图服务商的注册表。

这里只有数据，没有行为：新增一个服务商不必改 templates/maps.js。该模板把整份
注册表读成 JS 对象，切换时按 url/subdomains/tms/max_zoom 重建 L.TileLayer，按
coord_system 决定要不要把客户端坐标从 WGS-84 换算成 GCJ-02。

字段说明：
  name          服务商名。品牌词，不翻译。
  variant       同一服务商下的风格名（矢量/影像/浅色…），会翻译；空串表示不显示。
  url           瓦片 URL 模板，占位符与 Leaflet 一致（{s} {x} {y} {z}）。另有
                非 Leaflet 的 {key}，由 resolve_providers 在服务端替换掉。
  subdomains    传给 L.TileLayer 的 subdomains。url 里没有 {s} 时 Leaflet 不替换，
                写什么都无妨。
  tms           True 表示该服务 y 轴自下而上（TMS），Leaflet 会自行翻转。
  max_zoom      最大缩放级别，超过会请求到空白瓦片。
  attribution   版权声明。各家的授权条款要求随底图显示，换服务商时必须一起换。
  coord_system  'wgs84' 或 'gcj02'。gcj02 的底图在中国大陆有约 500m 的系统性偏移，
                标记坐标需要换算，否则会整体偏出街区。海外不受影响。
  key_setting   需要的配置项名；None 表示免 Key。
  note          给用户看的额外说明，没有则为空串。
"""

import logging
from flask_babel import gettext


def N_(message):
    """标记待翻译字符串。

    数据表在模块导入时构建，那时还没有请求上下文，不能直接调用 gettext；这里
    按 babel 的 gettext_noop 约定占个位，真正翻译推迟到 resolve_providers。
    注意 babel 只按字面量抽取 msgid，故这些字符串必须以字面量写在 N_() 里。
    """
    return message


# 顺序即下拉框顺序：先排中国大陆网络下实测可直连的，再把需要自备代理的排在后面。
MAP_PROVIDERS = {
    'amap': {
        'name': '高德地图',
        'variant': N_('Vector'),
        'url': ('https://webrd0{s}.is.autonavi.com/appmaptile'
                '?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}'),
        'subdomains': '1234',
        'tms': False,
        'max_zoom': 18,
        'attribution': '&copy; 高德地图',
        'coord_system': 'gcj02',
        'key_setting': None,
        'note': '',
    },
    'amap_sat': {
        'name': '高德地图',
        'variant': N_('Satellite'),
        'url': ('https://webst0{s}.is.autonavi.com/appmaptile'
                '?style=6&x={x}&y={y}&z={z}'),
        'subdomains': '1234',
        'tms': False,
        'max_zoom': 18,
        'attribution': '&copy; 高德地图',
        'coord_system': 'gcj02',
        'key_setting': None,
        'note': '',
    },
    'tencent': {
        'name': '腾讯地图',
        'variant': N_('Vector'),
        'url': ('https://rt{s}.map.gtimg.com/tile'
                '?z={z}&x={x}&y={y}&type=vector&styleid=7'),
        'subdomains': '0123',
        # 实测确认：腾讯瓦片的 y 轴自下而上，不翻转会整片请求到空白瓦片。
        'tms': True,
        'max_zoom': 18,
        'attribution': '&copy; 腾讯地图',
        'coord_system': 'gcj02',
        'key_setting': None,
        'note': '',
    },
    'tianditu': {
        # 天地图的球面墨卡托版（图层名以 _w 结尾）。它用的是 CGCS2000，与 WGS-84
        # 在本项目关心的精度下等价，故不需要坐标换算。
        'name': '天地图',
        'variant': N_('Vector'),
        'url': ('https://t{s}.tianditu.gov.cn/vec_w/wmts'
                '?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=vec'
                '&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles'
                '&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk={key}'),
        'subdomains': '01234567',
        'tms': False,
        'max_zoom': 18,
        'attribution': '&copy; 天地图',
        'coord_system': 'wgs84',
        'key_setting': 'map_tianditu_key',
        'note': '',
    },
    'esri': {
        'name': 'Esri',
        'variant': N_('Street'),
        'url': ('https://server.arcgisonline.com/ArcGIS/rest/services'
                '/World_Street_Map/MapServer/tile/{z}/{y}/{x}'),
        'subdomains': '',
        'tms': False,
        'max_zoom': 19,
        'attribution': 'Tiles &copy; Esri',
        'coord_system': 'wgs84',
        'key_setting': None,
        'note': '',
    },
    'esri_sat': {
        'name': 'Esri',
        'variant': N_('Imagery'),
        'url': ('https://server.arcgisonline.com/ArcGIS/rest/services'
                '/World_Imagery/MapServer/tile/{z}/{y}/{x}'),
        'subdomains': '',
        'tms': False,
        'max_zoom': 19,
        'attribution': 'Tiles &copy; Esri',
        'coord_system': 'wgs84',
        'key_setting': None,
        'note': '',
    },
    'osm': {
        'name': 'OpenStreetMap',
        'variant': N_('Standard'),
        'url': 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        'subdomains': '',
        'tms': False,
        'max_zoom': 19,
        'attribution': '&copy; OpenStreetMap contributors',
        'coord_system': 'wgs84',
        'key_setting': None,
        'note': N_('Overseas service; may need a proxy in China'),
    },
    'carto_light': {
        'name': 'CARTO',
        'variant': N_('Light'),
        'url': 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
        'subdomains': 'abcd',
        'tms': False,
        'max_zoom': 20,
        'attribution': '&copy; OpenStreetMap contributors &copy; CARTO',
        'coord_system': 'wgs84',
        'key_setting': None,
        'note': N_('Overseas service; may need a proxy in China'),
    },
    'carto_dark': {
        'name': 'CARTO',
        'variant': N_('Dark'),
        'url': 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
        'subdomains': 'abcd',
        'tms': False,
        'max_zoom': 20,
        'attribution': '&copy; OpenStreetMap contributors &copy; CARTO',
        'coord_system': 'wgs84',
        'key_setting': None,
        'note': N_('Overseas service; may need a proxy in China'),
    },
    'opentopomap': {
        'name': 'OpenTopoMap',
        'variant': N_('Terrain'),
        'url': 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
        'subdomains': 'abc',
        'tms': False,
        'max_zoom': 17,
        'attribution': '&copy; OpenStreetMap contributors, SRTM | &copy; OpenTopoMap (CC-BY-SA)',
        'coord_system': 'wgs84',
        'key_setting': None,
        'note': N_('Overseas service; may need a proxy in China'),
    },
}

# 配置文件里的 map_tile_url 呈现为这个额外的下拉项，供自建瓦片服务使用。
CUSTOM_PROVIDER_ID = 'custom'


def resolve_providers(settings):
    """把注册表整理成前端要用的列表，并挑出默认项。

    url 里的 {key} 在这里替换掉：前端既拿不到也不需要知道配置项名，缺 Key 时
    只是留一个不完整的 URL，反正不会被选中。

    返回 (providers, default_id)。providers 里的字典都是可 JSON 序列化的。
    """
    providers = []
    for provider_id, spec in MAP_PROVIDERS.items():
        item = _with_label(spec)
        key_setting = item.pop('key_setting')
        secret = (settings.get(key_setting) or '').strip() if key_setting else ''
        if key_setting:
            item['url'] = item['url'].replace('{key}', secret)
        item['id'] = provider_id
        item['needs_key'] = bool(key_setting)
        item['has_key'] = not key_setting or bool(secret)
        providers.append(item)

    # map_tile_url 在引入本注册表之前是唯一的换底图方式，为兼容既有部署仍予保留。
    # 它的子域与坐标系无从得知，取最常见的取值；版权声明留空，由使用方自行负责。
    custom_url = (settings.get('map_tile_url') or '').strip()
    if custom_url:
        providers.append({
            'id': CUSTOM_PROVIDER_ID,
            'name': gettext('Custom'),
            'label': gettext('Custom'),
            'url': custom_url,
            'subdomains': '1234',
            'tms': False,
            'max_zoom': 19,
            'attribution': '',
            'coord_system': 'wgs84',
            'needs_key': False,
            'has_key': True,
            'note': '',
        })

    return providers, _default_provider_id(settings, providers, custom_url)


def _with_label(spec):
    """复制一条记录，并把显示名拼好（品牌名不翻译，风格名与提示语翻译）。

    取值必须先落到局部变量再交给 gettext：写成 gettext(spec['variant']) 时
    babel 抽取的是下标里的字面量 'variant' 本身，既翻不到原文，还会往词条表里
    塞进 'variant'/'note' 这样的垃圾 msgid。
    """
    item = dict(spec)
    parts = [item['name']]
    variant = item['variant']
    note = item['note']
    if variant:
        parts.append(gettext(variant))
    if note:
        parts.append(gettext(note))
    item['label'] = ' · '.join(parts)
    return item


def _default_provider_id(settings, providers, custom_url):
    """确定初始底图。配置项无效或缺少所需 Key 时退回注册表里的第一个。"""
    by_id = {item['id']: item for item in providers}
    configured = (settings.get('map_provider') or '').strip()
    if configured:
        if configured not in by_id:
            logging.warning(f'Unknown map_provider `{configured}`, falling back')
        elif not by_id[configured]['has_key']:
            logging.warning(f'map_provider `{configured}` needs a key that is not set, falling back')
        else:
            return configured
    if custom_url:
        return CUSTOM_PROVIDER_ID
    return next(iter(MAP_PROVIDERS))
