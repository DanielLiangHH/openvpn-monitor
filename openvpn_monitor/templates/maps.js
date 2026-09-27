var map = L.map("map_canvas", { fullscreenControl: true, fullscreenControlOptions: { position: "topleft" } });
var centre = L.latLng({{ latitude }}, {{ longitude }});
map.setView(centre, 8);

var STORAGE_KEY = 'vpn-monitor-map-provider';
var DEFAULT_PROVIDER = {{ map_default_provider | tojson }};
var PROVIDER_LABEL = {{ map_provider_label | tojson }};
var MISSING_KEY = {{ map_provider_missing_key | tojson }};
// 只有配置文件显式给了经纬度，才把 centre 纳入取景范围。否则它是兜底的纽约
// 坐标，算进去会让地图横跨大洋、客户端标记被压成几个像素。
var CENTRE_CONFIGURED = {{ 'true' if map_centre_configured else 'false' }};

// 底图候选，全部来自 map_providers.py。增删服务商改那个文件即可，这里不必动。
var PROVIDERS = {{ map_providers | tojson }};

// 客户端坐标，一律 WGS-84（GeoIP 的原始输出），与当前底图无关。切到 GCJ-02
// 的底图时在渲染前临时换算，绝不回写本数组——否则来回切换会逐次累积偏移。
var CLIENT_POINTS = [
{%- for _, vpn in vpns -%}
{%- for _, session in vpn.get('sessions').items() if session.get('local_ip') -%}
{%- if session.get('latitude') and session.get('longitude') -%}
  {lat: {{ session.get('latitude') }}, lng: {{ session.get('longitude') }},
   html: {{ ("%s - %s" % (session.get('username'), session.get('remote_ip'))) | tojson }}},
{%- endif -%}
{%- endfor -%}
{%- endfor -%}
];

// ── 坐标换算 ────────────────────────────────────────────────────────────────
// 中国大陆的法规要求公开地图使用 GCJ-02（火星坐标系），高德/腾讯的瓦片因此相对
// 真实的 WGS-84 有约 500m 的系统性偏移，而 GeoIP 给的是 WGS-84。把 WGS-84 的点
// 直接画上去会整体偏出街区。下面是业界通用的近似算法，境内误差在米级，足够标点；
// 它只为显示服务，不要拿换算结果做距离或范围计算。境外不换算（算法只拟合了境内）。
var GCJ_A = 6378245.0;
var GCJ_EE = 0.00669342162296594323;

function outOfChina(lat, lng) {
  return lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271;
}

function transformLat(x, y) {
  var ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
  ret += (20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0 / 3.0;
  ret += (20.0 * Math.sin(y * Math.PI) + 40.0 * Math.sin(y / 3.0 * Math.PI)) * 2.0 / 3.0;
  ret += (160.0 * Math.sin(y / 12.0 * Math.PI) + 320.0 * Math.sin(y * Math.PI / 30.0)) * 2.0 / 3.0;
  return ret;
}

function transformLng(x, y) {
  var ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
  ret += (20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0 / 3.0;
  ret += (20.0 * Math.sin(x * Math.PI) + 40.0 * Math.sin(x / 3.0 * Math.PI)) * 2.0 / 3.0;
  ret += (150.0 * Math.sin(x / 12.0 * Math.PI) + 300.0 * Math.sin(x / 30.0 * Math.PI)) * 2.0 / 3.0;
  return ret;
}

function wgs84ToGcj02(lat, lng) {
  if (outOfChina(lat, lng)) {
    return [lat, lng];
  }
  var dLat = transformLat(lng - 105.0, lat - 35.0);
  var dLng = transformLng(lng - 105.0, lat - 35.0);
  var radLat = lat / 180.0 * Math.PI;
  var magic = Math.sin(radLat);
  magic = 1 - GCJ_EE * magic * magic;
  var sqrtMagic = Math.sqrt(magic);
  dLat = (dLat * 180.0) / ((GCJ_A * (1 - GCJ_EE)) / (magic * sqrtMagic) * Math.PI);
  dLng = (dLng * 180.0) / (GCJ_A / sqrtMagic * Math.cos(radLat) * Math.PI);
  return [lat + dLat, lng + dLng];
}

// ── 渲染 ────────────────────────────────────────────────────────────────────
var byId = {};
PROVIDERS.forEach(function (p) {
  byId[p.id] = p;
});

var tileLayer = null;
var markerLayer = L.layerGroup().addTo(map);
// 只在首次渲染时定视图。之后换底图保持用户当前的平移与缩放，否则刚放大到某个
// 城市又会被拽回全局。GCJ-02 换算带来的位移只有几百米，同一视野内仍看得见。
var viewFitted = false;

var popup = new L.Popup({closeButton:false, offset:new L.Point(0.5,-24)});
var oms = new OverlappingMarkerSpiderfier (map,{keepSpiderfied:true});
oms.addListener("click", function(marker) {
   popup.setContent(marker.alt);
   popup.setLatLng(marker.getLatLng());
   map.openPopup(popup);
});
oms.addListener("spiderfy", function(markers) {
   map.closePopup();
});

function render(providerId) {
  var provider = byId[providerId];
  if (!provider) {
    return;
  }

  // 子域、坐标系、最大级别都可能不同，只能整个换掉图层，不能只改 URL
  if (tileLayer) {
    map.removeLayer(tileLayer);
  }
  tileLayer = new L.TileLayer(provider.url, {
    subdomains: provider.subdomains,
    tms: provider.tms,
    maxZoom: provider.max_zoom,
    // 版权声明是各家授权条款的要求，必须随底图一起换
    attribution: provider.attribution
  });
  map.addLayer(tileLayer);

  // 重画标记：先按当前底图的坐标系投影，再挂到 OMS 上（它自己维护标记数组）
  oms.clearMarkers();
  markerLayer.clearLayers();
  var gcj02 = provider.coord_system === 'gcj02';
  var latlngs = [];
  CLIENT_POINTS.forEach(function (point) {
    var ll = gcj02 ? wgs84ToGcj02(point.lat, point.lng) : [point.lat, point.lng];
    var latlng = L.latLng(ll[0], ll[1]);
    latlngs.push(latlng);
    var marker = L.marker(latlng).addTo(markerLayer);
    marker.alt = point.html;
    oms.addMarker(marker);
    marker.bindPopup(L.popup().setLatLng(latlng).setContent(point.html));
  });

  // 没有任何客户端坐标时保持 setView 的初始视野
  if (!viewFitted && latlngs.length) {
    var bounds = L.latLngBounds(latlngs);
    if (CENTRE_CONFIGURED) {
      bounds.extend(centre);
    }
    map.fitBounds(bounds);
    viewFitted = true;
  }
}

// ── 底图切换控件 ────────────────────────────────────────────────────────────
// 放在地图内而不是导航栏：窄屏下导航栏收进汉堡菜单，放那里等于没有入口。
function storedProvider() {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch (e) {
    return null;
  }
}

function storeProvider(id) {
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch (e) {
    // 存不下时仅本次会话生效
  }
}

// 缺 Key 的服务商不能作为底图。它仍留在下拉框里，只是选中时会被拒。
function usable(id) {
  var provider = byId[id];
  return !!provider && (!provider.needs_key || provider.has_key);
}

function notify(text) {
  var el = L.DomUtil.create('div', 'vpn-map-notice', map.getContainer());
  el.setAttribute('role', 'status');
  el.textContent = text;
  window.setTimeout(function () {
    el.classList.add('vpn-map-notice--leaving');
    window.setTimeout(function () {
      if (el.parentNode) {
        el.parentNode.removeChild(el);
      }
    }, 400);
  }, 4000);
}

var ProviderControl = L.Control.extend({
  options: { position: 'topright' },

  onAdd: function () {
    var wrap = L.DomUtil.create('div', 'vpn-map-provider');
    var select = L.DomUtil.create('select', 'vpn-map-provider__select', wrap);
    select.setAttribute('aria-label', PROVIDER_LABEL);
    select.setAttribute('title', PROVIDER_LABEL);
    PROVIDERS.forEach(function (provider) {
      var option = L.DomUtil.create('option', '', select);
      option.value = provider.id;
      option.textContent = provider.label;
    });
    select.value = currentId;
    // 不放行点击与滚轮：否则点下拉框会同时拖拽地图，在上面滚轮会缩放地图
    L.DomEvent.disableClickPropagation(wrap);
    L.DomEvent.disableScrollPropagation(wrap);
    L.DomEvent.on(select, 'change', function () {
      if (!usable(select.value)) {
        // 提示后把下拉框拨回当前生效的服务商，地图保持不动
        notify(MISSING_KEY);
        select.value = currentId;
        return;
      }
      currentId = select.value;
      storeProvider(currentId);
      render(currentId);
    });
    return wrap;
  }
});

// 初始底图：优先本浏览器上次的选择，其次配置文件的 map_provider（已由服务端
// 校验过），最后注册表首项。上次选的服务商若已失去 Key（配置被撤走），静默退回，
// 不在页面加载时就弹提示。
var currentId = storedProvider();
if (!usable(currentId)) {
  currentId = usable(DEFAULT_PROVIDER) ? DEFAULT_PROVIDER : PROVIDERS[0].id;
}

map.addControl(new ProviderControl());
render(currentId);
