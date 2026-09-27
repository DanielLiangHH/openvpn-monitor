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

import logging
import os
import secrets
import sys
from datetime import datetime
from flask import Flask, request, render_template, send_file, current_app
from flask_babel import Babel, get_locale, gettext, ngettext
from flask_wtf import CSRFProtect
from humanize import naturalsize
from pprint import pformat

cwd = os.path.dirname(__file__)
os.chdir(cwd)
sys.path.append(cwd)
from config.loader import ConfigLoader                    # noqa
from vpns.openvpn.data_collector import VPNDataCollector  # noqa
from vpns.openvpn.disconnector import VPNDisconnector     # noqa
from location_data.maxmind.geoip import GeoipDBLoader     # noqa
from map_providers import resolve_providers               # noqa
from util import is_truthy                                # noqa

logging.basicConfig(stream=sys.stderr, format='[%(asctime)s] [%(process)d] [%(levelname)s] %(message)s')
logging.getLogger().setLevel(logging.INFO)

# 地图中心点的兜底坐标（上游作者所在地）。配置文件未指定 latitude/longitude
# 时会落到这里；maps.js 用 map_centre_configured 判断是否该把该点纳入取景范围。
DEFAULT_MAP_LATITUDE = 40.72
DEFAULT_MAP_LONGITUDE = -74


def openvpn_monitor_wsgi():

    app = Flask(__name__)
    app.url_map.strict_slashes = False
    csrf = CSRFProtect(app)
    csrf.init_app(app)
    secret_key = secrets.token_hex(16)
    app.secret_key = secret_key

    # 翻译目录默认为 app root_path 下的 translations/，即 openvpn_monitor/translations
    babel = Babel(app, default_locale='zh_CN')

    if app.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    config_file = os.getenv('OPENVPNMONITOR_CONFIG_FILE', '/etc/openvpn-monitor/openvpn-monitor.conf')
    config = ConfigLoader(config_file)
    settings = config.settings
    # Dockerfile 自 1.0.2 起设置了 ENABLE_MAPS / GEOIP_DATA 环境变量，但本项目
    # 从不读取它们（上游从未支持过），容器化部署因此拿不到 GeoIP 库，地图上
    # 一个客户端标记都不会有。这里把环境变量作为配置文件的后备，配置文件优先。
    for env_key, conf_key in (('ENABLE_MAPS', 'enable_maps'), ('GEOIP_DATA', 'geoip_data')):
        if conf_key not in settings and os.getenv(env_key):
            settings[conf_key] = os.getenv(env_key)
    loaded_vpns = config.vpns
    geoip_db = GeoipDBLoader(settings)

    @app.template_filter()
    def get_formatted_time_now(datetime_format):
        return datetime.now().strftime(datetime_format)

    @app.template_filter()
    def get_vpn_anchor(vpn):
        if vpn.get('name'):
            return vpn.get('name').lower().replace(' ', '_')

    @app.template_filter()
    def get_naturalsize(nbytes):
        if nbytes:
            return naturalsize(nbytes, binary=True)

    @app.template_filter()
    def get_full_location(session):
        full_location = ''
        location = session.get('location')
        if location:
            if location in ['RFC1918', 'loopback']:
                city = location
                country = 'Internet'
                full_location = f'{city}, {country}'
            else:
                if session.get('country'):
                    country = session.get('country')
                    full_location = country
                if session.get('region'):
                    region = session.get('region')
                    full_location = f'{region}, {full_location}'
                if session.get('city'):
                    city = session.get('city')
                    full_location = f'{city}, {full_location}'
        return full_location

    @app.template_filter()
    def get_flag(session):
        flag = ''
        location = session.get('location')
        if location:
            if location in ['RFC1918', 'loopback']:
                flag = 'images/flags/rfc.png'
            else:
                flag = f'images/flags/{location.lower()}.png'
        return flag

    @app.template_filter()
    def get_vpn_error(vpn):
        name = vpn.get('name')
        host = vpn.get('host')
        port = vpn.get('port')
        socket = vpn.get('socket')
        error = vpn.get('error')
        if host and port:
            return f'{host}:{port} ({error})'
        elif socket:
            return f'{socket} ({error})'
        else:
            logging.error(f'unknown error with vpn {name} - {error}')
            return f'network or unix socket ({error})'

    @app.template_filter()
    def get_session_headers(vpn_mode):
        server_headers = [
            gettext('Username / Hostname'),
            gettext('VPN IP'),
            gettext('Remote IP'),
            gettext('Location'),
            gettext('Bytes In'),
            gettext('Bytes Out'),
            gettext('Connected Since'),
            gettext('Last Ping'),
            gettext('Time Online')
        ]
        client_headers = [
            gettext('Tun-Tap-Read'),
            gettext('Tun-Tap-Write'),
            gettext('TCP-UDP-Read'),
            gettext('TCP-UDP-Write'),
            gettext('Auth-Read')
        ]
        if vpn_mode == 'Client':
            headers = client_headers
        elif vpn_mode == 'Server':
            headers = server_headers
        return headers

    @app.template_filter()
    def get_total_connected_time(connected_since):
        # 原实现直接截取 timedelta 的字符串形式（如 '2 days, 7:39:39'）。
        # 天数部分由 timedelta.__str__ 生成、受 locale 影响不可控，
        # 故改为自行拆解，保证中文输出为 '2 天 07:39:39'。
        delta = datetime.now() - connected_since
        days, remainder = delta.days, delta.seconds
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        if not days:
            return f'{hours}:{minutes:02d}:{seconds:02d}'
        day_part = ngettext('%(num)d day', '%(num)d days', days) % {'num': days}
        return f'{day_part} {hours:02d}:{minutes:02d}:{seconds:02d}'

    @app.context_processor
    def inject_settings():
        site = settings.get('site', 'Example')
        logo = settings.get('logo')
        enable_maps = is_truthy(settings.get('enable_maps', False))
        maps_height = settings.get('maps_height', 500)
        # 底图由前端下拉框切换，作用范围只在本浏览器（localStorage），故这里
        # 一次给出全部候选，由 JS 决定实际加载哪一个。
        map_providers, map_default_provider = resolve_providers(settings)
        latitude = settings.get('latitude', DEFAULT_MAP_LATITUDE)
        longitude = settings.get('longitude', DEFAULT_MAP_LONGITUDE)
        # 只有配置文件显式给了经纬度，才把这个点纳入地图取景范围。否则默认值会把
        # 视图拉到横跨大洋的世界级缩放，客户端标记全被压成几个像素。
        map_centre_configured = 'latitude' in settings and 'longitude' in settings
        datetime_format = settings.get('datetime_format', '%d/%m/%Y %H:%M:%S')
        # Flask-Babel 只向 Jinja 注册了 _ / gettext / ngettext，并未注册 get_locale，
        # 故在此注入。get_locale() 返回 Locale 对象，str() 为 zh_Hans_CN，
        # 转成 BCP47 供 <html lang> 使用。
        locale = str(get_locale()).replace('_', '-')
        return dict(
            site=site,
            logo=logo,
            enable_maps=enable_maps,
            maps_height=maps_height,
            map_providers=map_providers,
            map_default_provider=map_default_provider,
            # maps.js 后缀是 .js，不在 babel.cfg 的抽取范围内，故其界面文案
            # 一律在 Python 侧翻译好再传过去。
            map_provider_label=gettext('Map Provider'),
            map_provider_missing_key=gettext('No API key is configured for this '
                                             'map provider. Reverted to the default map.'),
            latitude=latitude,
            longitude=longitude,
            map_centre_configured=map_centre_configured,
            datetime_format=datetime_format,
            locale=locale,
        )

    @app.route('/images/logo', methods=['GET'])
    def get_logo():
        logo = settings.get('logo')
        if not logo:
            logging.warning('No logo defined in settings')
            return '', 204
        if logo.startswith('http'):
            logging.info(f'Using `{logo}` for logo (http link)')
            return logo
        logo_file = os.path.join('/etc/openvpn-monitor', logo)
        if os.path.isfile(logo_file) and os.access(logo_file, os.R_OK):
            logging.info(f'Using `{logo_file}` for logo')
            return send_file(logo_file)
        logo_file = os.path.join(cwd, 'static/images', logo)
        if os.path.isfile(logo_file) and os.access(logo_file, os.R_OK):
            static_logo = f'images/{logo}'
            logging.info(f'Using `{logo_file}` for logo (static)')
            return current_app.send_static_file(static_logo)
        logging.error(f'Logo defined but image not found, skipping')
        return '', 404

    @app.route('/', methods=['GET', 'POST'])
    def handle_root():
        vpn_data = VPNDataCollector(loaded_vpns, geoip_db.gi)
        vpns = vpn_data.vpns.items()
        pretty_vpns = pformat((dict(vpns)))
        logging.debug(f'=== begin vpns\n{pretty_vpns}\n=== end vpns')
        if request.method == 'GET':
            return render_template('base.html', vpns=vpns)
        elif request.method == 'POST':
            vpn_id = request.form.get('vpn_id')
            ip = request.form.get('ip')
            port = request.form.get('port')
            client_id = request.form.get('client_id')
            VPNDisconnector(
                vpns=vpns,
                vpn_id=vpn_id,
                ip=ip,
                port=port,
                client_id=client_id,
            )
            return render_template('base.html', vpns=vpns)

    return app


application = openvpn_monitor_wsgi()
