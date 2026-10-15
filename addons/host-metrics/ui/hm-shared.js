const runtime = typeof window !== "undefined" ? window.__qlsm : void 0;
if (!runtime || !runtime.react || !runtime.ui) {
  throw new Error(
    "host-metrics: window.__qlsm.react is not published. This bundle only runs inside QLSM, which publishes its React and UI kit before mounting an addon component."
  );
}
const React = runtime.react;
const {
  Fragment,
  createElement,
  useCallback: useCallback$1,
  useEffect: useEffect$2,
  useMemo: useMemo$2,
  useRef: useRef$2,
  useState: useState$2
} = React;
const ui = runtime.ui;
function Button({ variant = "secondary", className = "", ...rest }) {
  if (ui.Button) return React.createElement(ui.Button, { variant, className, ...rest });
  const cls = `hm-btn${variant === "primary" ? " hm-btn-primary" : ""}${className ? ` ${className}` : ""}`;
  return React.createElement("button", { type: "button", className: cls, ...rest });
}
const FEAT_TIME = true;
const pre = "u-";
const UPLOT = "uplot";
const ORI_HZ = pre + "hz";
const ORI_VT = pre + "vt";
const TITLE = pre + "title";
const WRAP = pre + "wrap";
const UNDER = pre + "under";
const OVER = pre + "over";
const AXIS = pre + "axis";
const OFF = pre + "off";
const SELECT = pre + "select";
const CURSOR_X = pre + "cursor-x";
const CURSOR_Y = pre + "cursor-y";
const CURSOR_PT = pre + "cursor-pt";
const LEGEND = pre + "legend";
const LEGEND_LIVE = pre + "live";
const LEGEND_INLINE = pre + "inline";
const LEGEND_SERIES = pre + "series";
const LEGEND_MARKER = pre + "marker";
const LEGEND_LABEL = pre + "label";
const LEGEND_VALUE = pre + "value";
const WIDTH = "width";
const HEIGHT = "height";
const TOP = "top";
const BOTTOM = "bottom";
const LEFT = "left";
const RIGHT = "right";
const hexBlack = "#000";
const transparent = hexBlack + "0";
const mousemove = "mousemove";
const mousedown = "mousedown";
const mouseup = "mouseup";
const mouseenter = "mouseenter";
const mouseleave = "mouseleave";
const dblclick = "dblclick";
const resize = "resize";
const scroll = "scroll";
const change = "change";
const dppxchange = "dppxchange";
const LEGEND_DISP = "--";
const domEnv = typeof window != "undefined";
const doc = domEnv ? document : null;
const win = domEnv ? window : null;
const nav = domEnv ? navigator : null;
let pxRatio;
let query;
function setPxRatio() {
  let _pxRatio = devicePixelRatio;
  if (pxRatio != _pxRatio) {
    pxRatio = _pxRatio;
    query && off(change, query, setPxRatio);
    query = matchMedia(`(min-resolution: ${pxRatio - 1e-3}dppx) and (max-resolution: ${pxRatio + 1e-3}dppx)`);
    on(change, query, setPxRatio);
    win.dispatchEvent(new CustomEvent(dppxchange));
  }
}
function addClass(el, c) {
  if (c != null) {
    let cl = el.classList;
    !cl.contains(c) && cl.add(c);
  }
}
function remClass(el, c) {
  let cl = el.classList;
  cl.contains(c) && cl.remove(c);
}
function setStylePx(el, name, value) {
  el.style[name] = value + "px";
}
function placeTag(tag, cls, targ, refEl) {
  let el = doc.createElement(tag);
  if (cls != null)
    addClass(el, cls);
  if (targ != null)
    targ.insertBefore(el, refEl);
  return el;
}
function placeDiv(cls, targ) {
  return placeTag("div", cls, targ);
}
const xformCache = /* @__PURE__ */ new WeakMap();
function elTrans(el, xPos, yPos, xMax, yMax) {
  let xform = "translate(" + xPos + "px," + yPos + "px)";
  let xformOld = xformCache.get(el);
  if (xform != xformOld) {
    el.style.transform = xform;
    xformCache.set(el, xform);
    if (xPos < 0 || yPos < 0 || xPos > xMax || yPos > yMax)
      addClass(el, OFF);
    else
      remClass(el, OFF);
  }
}
const colorCache = /* @__PURE__ */ new WeakMap();
function elColor(el, background, borderColor) {
  let newColor = background + borderColor;
  let oldColor = colorCache.get(el);
  if (newColor != oldColor) {
    colorCache.set(el, newColor);
    el.style.background = background;
    el.style.borderColor = borderColor;
  }
}
const sizeCache = /* @__PURE__ */ new WeakMap();
function elSize(el, newWid, newHgt, centered) {
  let newSize = newWid + "" + newHgt;
  let oldSize = sizeCache.get(el);
  if (newSize != oldSize) {
    sizeCache.set(el, newSize);
    el.style.height = newHgt + "px";
    el.style.width = newWid + "px";
    el.style.marginLeft = centered ? -newWid / 2 + "px" : 0;
    el.style.marginTop = centered ? -newHgt / 2 + "px" : 0;
  }
}
const evOpts = { passive: true };
const evOpts2 = { ...evOpts, capture: true };
function on(ev, el, cb, capt) {
  el.addEventListener(ev, cb, capt ? evOpts2 : evOpts);
}
function off(ev, el, cb, capt) {
  el.removeEventListener(ev, cb, evOpts);
}
domEnv && setPxRatio();
function closestIdx(num2, arr, lo, hi) {
  let mid;
  lo = lo || 0;
  hi = hi || arr.length - 1;
  let bitwise = hi <= 2147483647;
  while (hi - lo > 1) {
    mid = bitwise ? lo + hi >> 1 : floor((lo + hi) / 2);
    if (arr[mid] < num2)
      lo = mid;
    else
      hi = mid;
  }
  if (num2 - arr[lo] <= arr[hi] - num2)
    return lo;
  return hi;
}
function nonNullIdx(data, _i0, _i1, dir) {
  for (let i = dir == 1 ? _i0 : _i1; i >= _i0 && i <= _i1; i += dir) {
    if (data[i] != null)
      return i;
  }
  return -1;
}
function getMinMax(data, _i0, _i1, sorted) {
  let _min = inf;
  let _max = -inf;
  if (sorted == 1) {
    _min = data[_i0];
    _max = data[_i1];
  } else if (sorted == -1) {
    _min = data[_i1];
    _max = data[_i0];
  } else {
    for (let i = _i0; i <= _i1; i++) {
      let v = data[i];
      if (v != null) {
        if (v < _min)
          _min = v;
        if (v > _max)
          _max = v;
      }
    }
  }
  return [_min, _max];
}
function getMinMaxLog(data, _i0, _i1) {
  let _min = inf;
  let _max = -inf;
  for (let i = _i0; i <= _i1; i++) {
    let v = data[i];
    if (v != null && v > 0) {
      if (v < _min)
        _min = v;
      if (v > _max)
        _max = v;
    }
  }
  return [_min, _max];
}
function rangeLog(min2, max2, base, fullMags) {
  let minSign = sign(min2);
  let maxSign = sign(max2);
  if (min2 == max2) {
    if (minSign == -1) {
      min2 *= base;
      max2 /= base;
    } else {
      min2 /= base;
      max2 *= base;
    }
  }
  let logFn = base == 10 ? log10 : log2;
  let growMinAbs = minSign == 1 ? floor : ceil;
  let growMaxAbs = maxSign == 1 ? ceil : floor;
  let minExp = growMinAbs(logFn(abs(min2)));
  let maxExp = growMaxAbs(logFn(abs(max2)));
  let minIncr = pow(base, minExp);
  let maxIncr = pow(base, maxExp);
  if (base == 10) {
    if (minExp < 0)
      minIncr = roundDec(minIncr, -minExp);
    if (maxExp < 0)
      maxIncr = roundDec(maxIncr, -maxExp);
  }
  if (fullMags || base == 2) {
    min2 = minIncr * minSign;
    max2 = maxIncr * maxSign;
  } else {
    min2 = incrRoundDn(min2, minIncr);
    max2 = incrRoundUp(max2, maxIncr);
  }
  return [min2, max2];
}
function rangeAsinh(min2, max2, base, fullMags) {
  let minMax = rangeLog(min2, max2, base, fullMags);
  if (min2 == 0)
    minMax[0] = 0;
  if (max2 == 0)
    minMax[1] = 0;
  return minMax;
}
const rangePad = 0.1;
const autoRangePart = {
  mode: 3,
  pad: rangePad
};
const _eqRangePart = {
  pad: 0,
  soft: null,
  mode: 0
};
const _eqRange = {
  min: _eqRangePart,
  max: _eqRangePart
};
function rangeNum(_min, _max, mult, extra) {
  if (isObj(mult))
    return _rangeNum(_min, _max, mult);
  _eqRangePart.pad = mult;
  _eqRangePart.soft = extra ? 0 : null;
  _eqRangePart.mode = extra ? 3 : 0;
  return _rangeNum(_min, _max, _eqRange);
}
function ifNull(lh, rh) {
  return lh == null ? rh : lh;
}
function hasData(data, idx0, idx1) {
  idx0 = ifNull(idx0, 0);
  idx1 = ifNull(idx1, data.length - 1);
  while (idx0 <= idx1) {
    if (data[idx0] != null)
      return true;
    idx0++;
  }
  return false;
}
function _rangeNum(_min, _max, cfg) {
  let cmin = cfg.min;
  let cmax = cfg.max;
  let padMin = ifNull(cmin.pad, 0);
  let padMax = ifNull(cmax.pad, 0);
  let hardMin = ifNull(cmin.hard, -inf);
  let hardMax = ifNull(cmax.hard, inf);
  let softMin = ifNull(cmin.soft, inf);
  let softMax = ifNull(cmax.soft, -inf);
  let softMinMode = ifNull(cmin.mode, 0);
  let softMaxMode = ifNull(cmax.mode, 0);
  let delta = _max - _min;
  let deltaMag = log10(delta);
  let scalarMax = max(abs(_min), abs(_max));
  let scalarMag = log10(scalarMax);
  let scalarMagDelta = abs(scalarMag - deltaMag);
  if (delta < 1e-24 || scalarMagDelta > 10) {
    delta = 0;
    if (_min == 0 || _max == 0) {
      delta = 1e-24;
      if (softMinMode == 2 && softMin != inf)
        padMin = 0;
      if (softMaxMode == 2 && softMax != -inf)
        padMax = 0;
    }
  }
  let nonZeroDelta = delta || scalarMax || 1e3;
  let mag = log10(nonZeroDelta);
  let base = pow(10, floor(mag));
  let _padMin = nonZeroDelta * (delta == 0 ? _min == 0 ? 0.1 : 1 : padMin);
  let _newMin = roundDec(incrRoundDn(_min - _padMin, base / 10), 24);
  let _softMin = _min >= softMin && (softMinMode == 1 || softMinMode == 3 && _newMin <= softMin || softMinMode == 2 && _newMin >= softMin) ? softMin : inf;
  let minLim = max(hardMin, _newMin < _softMin && _min >= _softMin ? _softMin : min(_softMin, _newMin));
  let _padMax = nonZeroDelta * (delta == 0 ? _max == 0 ? 0.1 : 1 : padMax);
  let _newMax = roundDec(incrRoundUp(_max + _padMax, base / 10), 24);
  let _softMax = _max <= softMax && (softMaxMode == 1 || softMaxMode == 3 && _newMax >= softMax || softMaxMode == 2 && _newMax <= softMax) ? softMax : -inf;
  let maxLim = min(hardMax, _newMax > _softMax && _max <= _softMax ? _softMax : max(_softMax, _newMax));
  if (minLim == maxLim && minLim == 0)
    maxLim = 100;
  return [minLim, maxLim];
}
const numFormatter = new Intl.NumberFormat(domEnv ? nav.language : "en-US");
const fmtNum = (val) => numFormatter.format(val);
const M = Math;
const PI = M.PI;
const abs = M.abs;
const floor = M.floor;
const round = M.round;
const ceil = M.ceil;
const min = M.min;
const max = M.max;
const pow = M.pow;
const sign = M.sign;
const log10 = M.log10;
const log2 = M.log2;
const sinh = (v, linthresh = 1) => M.sinh(v) * linthresh;
const asinh = (v, linthresh = 1) => M.asinh(v / linthresh);
const inf = Infinity;
function numIntDigits(x) {
  return (log10((x ^ x >> 31) - (x >> 31)) | 0) + 1;
}
function clamp(num2, _min, _max) {
  return min(max(num2, _min), _max);
}
function fnOrSelf(v) {
  return typeof v == "function" ? v : () => v;
}
const noop = () => {
};
const retArg0 = (_0) => _0;
const retArg1 = (_0, _1) => _1;
const retNull = (_2) => null;
const retTrue = (_2) => true;
const retEq = (a, b) => a == b;
const regex6 = /\.\d*?(?=9{6,}|0{6,})/gm;
const fixFloat = (val) => {
  if (isInt(val) || fixedDec.has(val))
    return val;
  const str = `${val}`;
  const match = str.match(regex6);
  if (match == null)
    return val;
  let len = match[0].length - 1;
  if (str.indexOf("e-") != -1) {
    let [num2, exp] = str.split("e");
    return +`${fixFloat(num2)}e${exp}`;
  }
  return roundDec(val, len);
};
function incrRound(num2, incr) {
  return fixFloat(roundDec(fixFloat(num2 / incr)) * incr);
}
function incrRoundUp(num2, incr) {
  return fixFloat(ceil(fixFloat(num2 / incr)) * incr);
}
function incrRoundDn(num2, incr) {
  return fixFloat(floor(fixFloat(num2 / incr)) * incr);
}
function roundDec(val, dec = 0) {
  if (isInt(val))
    return val;
  let p = 10 ** dec;
  let n = val * p * (1 + Number.EPSILON);
  return round(n) / p;
}
const fixedDec = /* @__PURE__ */ new Map();
function guessDec(num2) {
  return (("" + num2).split(".")[1] || "").length;
}
function genIncrs(base, minExp, maxExp, mults) {
  let incrs = [];
  let multDec = mults.map(guessDec);
  for (let exp = minExp; exp < maxExp; exp++) {
    let expa = abs(exp);
    let mag = roundDec(pow(base, exp), expa);
    for (let i = 0; i < mults.length; i++) {
      let _incr = base == 10 ? +`${mults[i]}e${exp}` : mults[i] * mag;
      let dec = (exp >= 0 ? 0 : expa) + (exp >= multDec[i] ? 0 : multDec[i]);
      let incr = base == 10 ? _incr : roundDec(_incr, dec);
      incrs.push(incr);
      fixedDec.set(incr, dec);
    }
  }
  return incrs;
}
const EMPTY_OBJ = {};
const EMPTY_ARR = [];
const nullNullTuple = [null, null];
const isArr = Array.isArray;
const isInt = Number.isInteger;
const isUndef = (v) => v === void 0;
function isStr(v) {
  return typeof v == "string";
}
function isObj(v) {
  let is = false;
  if (v != null) {
    let c = v.constructor;
    is = c == null || c == Object;
  }
  return is;
}
function fastIsObj(v) {
  return v != null && typeof v == "object";
}
const TypedArray = Object.getPrototypeOf(Uint8Array);
const __proto__ = "__proto__";
function copy(o, _isObj = isObj) {
  let out;
  if (isArr(o)) {
    let val = o.find((v) => v != null);
    if (isArr(val) || _isObj(val)) {
      out = Array(o.length);
      for (let i = 0; i < o.length; i++)
        out[i] = copy(o[i], _isObj);
    } else
      out = o.slice();
  } else if (o instanceof TypedArray)
    out = o.slice();
  else if (_isObj(o)) {
    out = {};
    for (let k in o) {
      if (k != __proto__)
        out[k] = copy(o[k], _isObj);
    }
  } else
    out = o;
  return out;
}
function assign(targ) {
  let args = arguments;
  for (let i = 1; i < args.length; i++) {
    let src = args[i];
    for (let key in src) {
      if (key != __proto__) {
        if (isObj(targ[key]))
          assign(targ[key], copy(src[key]));
        else
          targ[key] = copy(src[key]);
      }
    }
  }
  return targ;
}
const NULL_REMOVE = 0;
const NULL_RETAIN = 1;
const NULL_EXPAND = 2;
function nullExpand(yVals, nullIdxs, alignedLen) {
  for (let i = 0, xi, lastNullIdx = -1; i < nullIdxs.length; i++) {
    let nullIdx = nullIdxs[i];
    if (nullIdx > lastNullIdx) {
      xi = nullIdx - 1;
      while (xi >= 0 && yVals[xi] == null)
        yVals[xi--] = null;
      xi = nullIdx + 1;
      while (xi < alignedLen && yVals[xi] == null)
        yVals[lastNullIdx = xi++] = null;
    }
  }
}
function join(tables, nullModes) {
  if (allHeadersSame(tables)) {
    let table = tables[0].slice();
    for (let i = 1; i < tables.length; i++)
      table.push(...tables[i].slice(1));
    if (!isAsc(table[0]))
      table = sortCols(table);
    return table;
  }
  let xVals = /* @__PURE__ */ new Set();
  for (let ti = 0; ti < tables.length; ti++) {
    let t = tables[ti];
    let xs = t[0];
    let len = xs.length;
    for (let i = 0; i < len; i++)
      xVals.add(xs[i]);
  }
  let data = [Array.from(xVals).sort((a, b) => a - b)];
  let alignedLen = data[0].length;
  let xIdxs = /* @__PURE__ */ new Map();
  for (let i = 0; i < alignedLen; i++)
    xIdxs.set(data[0][i], i);
  for (let ti = 0; ti < tables.length; ti++) {
    let t = tables[ti];
    let xs = t[0];
    for (let si = 1; si < t.length; si++) {
      let ys = t[si];
      let yVals = Array(alignedLen).fill(void 0);
      let nullMode = nullModes ? nullModes[ti][si] : NULL_RETAIN;
      let nullIdxs = [];
      for (let i = 0; i < ys.length; i++) {
        let yVal = ys[i];
        let alignedIdx = xIdxs.get(xs[i]);
        if (yVal === null) {
          if (nullMode != NULL_REMOVE) {
            yVals[alignedIdx] = yVal;
            if (nullMode == NULL_EXPAND)
              nullIdxs.push(alignedIdx);
          }
        } else
          yVals[alignedIdx] = yVal;
      }
      nullExpand(yVals, nullIdxs, alignedLen);
      data.push(yVals);
    }
  }
  return data;
}
const microTask = typeof queueMicrotask == "undefined" ? (fn) => Promise.resolve().then(fn) : queueMicrotask;
function sortCols(table) {
  let head = table[0];
  let rlen = head.length;
  let idxs = Array(rlen);
  for (let i = 0; i < idxs.length; i++)
    idxs[i] = i;
  idxs.sort((i0, i1) => head[i0] - head[i1]);
  let table2 = [];
  for (let i = 0; i < table.length; i++) {
    let row = table[i];
    let row2 = Array(rlen);
    for (let j = 0; j < rlen; j++)
      row2[j] = row[idxs[j]];
    table2.push(row2);
  }
  return table2;
}
function allHeadersSame(tables) {
  let vals0 = tables[0][0];
  let len0 = vals0.length;
  for (let i = 1; i < tables.length; i++) {
    let vals1 = tables[i][0];
    if (vals1.length != len0)
      return false;
    if (vals1 != vals0) {
      for (let j = 0; j < len0; j++) {
        if (vals1[j] != vals0[j])
          return false;
      }
    }
  }
  return true;
}
function isAsc(vals, samples = 100) {
  const len = vals.length;
  if (len <= 1)
    return true;
  let firstIdx = 0;
  let lastIdx = len - 1;
  while (firstIdx <= lastIdx && vals[firstIdx] == null)
    firstIdx++;
  while (lastIdx >= firstIdx && vals[lastIdx] == null)
    lastIdx--;
  if (lastIdx <= firstIdx)
    return true;
  const stride = max(1, floor((lastIdx - firstIdx + 1) / samples));
  for (let prevVal = vals[firstIdx], i = firstIdx + stride; i <= lastIdx; i += stride) {
    const v = vals[i];
    if (v != null) {
      if (v <= prevVal)
        return false;
      prevVal = v;
    }
  }
  return true;
}
const months = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December"
];
const days = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday"
];
function slice3(str) {
  return str.slice(0, 3);
}
const days3 = days.map(slice3);
const months3 = months.map(slice3);
const engNames = {
  MMMM: months,
  MMM: months3,
  WWWW: days,
  WWW: days3
};
function zeroPad2(int2) {
  return (int2 < 10 ? "0" : "") + int2;
}
function zeroPad3(int2) {
  return (int2 < 10 ? "00" : int2 < 100 ? "0" : "") + int2;
}
const subs = {
  // 2019
  YYYY: (d) => d.getFullYear(),
  // 19
  YY: (d) => (d.getFullYear() + "").slice(2),
  // July
  MMMM: (d, names) => names.MMMM[d.getMonth()],
  // Jul
  MMM: (d, names) => names.MMM[d.getMonth()],
  // 07
  MM: (d) => zeroPad2(d.getMonth() + 1),
  // 7
  M: (d) => d.getMonth() + 1,
  // 09
  DD: (d) => zeroPad2(d.getDate()),
  // 9
  D: (d) => d.getDate(),
  // Monday
  WWWW: (d, names) => names.WWWW[d.getDay()],
  // Mon
  WWW: (d, names) => names.WWW[d.getDay()],
  // 03
  HH: (d) => zeroPad2(d.getHours()),
  // 3
  H: (d) => d.getHours(),
  // 9 (12hr, unpadded)
  h: (d) => {
    let h = d.getHours();
    return h == 0 ? 12 : h > 12 ? h - 12 : h;
  },
  // AM
  AA: (d) => d.getHours() >= 12 ? "PM" : "AM",
  // am
  aa: (d) => d.getHours() >= 12 ? "pm" : "am",
  // a
  a: (d) => d.getHours() >= 12 ? "p" : "a",
  // 09
  mm: (d) => zeroPad2(d.getMinutes()),
  // 9
  m: (d) => d.getMinutes(),
  // 09
  ss: (d) => zeroPad2(d.getSeconds()),
  // 9
  s: (d) => d.getSeconds(),
  // 374
  fff: (d) => zeroPad3(d.getMilliseconds())
};
function fmtDate(tpl, names) {
  names = names || engNames;
  let parts = [];
  let R = /\{([a-z]+)\}|[^{]+/gi, m;
  while (m = R.exec(tpl))
    parts.push(m[0][0] == "{" ? subs[m[1]] : m[0]);
  return (d) => {
    let out = "";
    for (let i = 0; i < parts.length; i++)
      out += typeof parts[i] == "string" ? parts[i] : parts[i](d, names);
    return out;
  };
}
const localTz = new Intl.DateTimeFormat().resolvedOptions().timeZone;
function tzDate(date, tz) {
  let date2;
  if (tz == "UTC" || tz == "Etc/UTC")
    date2 = new Date(+date + date.getTimezoneOffset() * 6e4);
  else if (tz == localTz)
    date2 = date;
  else {
    date2 = new Date(date.toLocaleString("en-US", { timeZone: tz }));
    date2.setMilliseconds(date.getMilliseconds());
  }
  return date2;
}
const onlyWhole = (v) => v % 1 == 0;
const allMults = [1, 2, 2.5, 5];
const decIncrs = genIncrs(10, -32, 0, allMults);
const oneIncrs = genIncrs(10, 0, 32, allMults);
const wholeIncrs = oneIncrs.filter(onlyWhole);
const numIncrs = decIncrs.concat(oneIncrs);
const NL = "\n";
const yyyy = "{YYYY}";
const NLyyyy = NL + yyyy;
const md = "{M}/{D}";
const NLmd = NL + md;
const NLmdyy = NLmd + "/{YY}";
const aa = "{aa}";
const hmm = "{h}:{mm}";
const hmmaa = hmm + aa;
const NLhmmaa = NL + hmmaa;
const ss = ":{ss}";
const _ = null;
function genTimeStuffs(ms2) {
  let s = ms2 * 1e3, m = s * 60, h = m * 60, d = h * 24, mo = d * 30, y = d * 365;
  let subSecIncrs = ms2 == 1 ? genIncrs(10, 0, 3, allMults).filter(onlyWhole) : genIncrs(10, -3, 0, allMults);
  let timeIncrs = subSecIncrs.concat([
    // minute divisors (# of secs)
    s,
    s * 5,
    s * 10,
    s * 15,
    s * 30,
    // hour divisors (# of mins)
    m,
    m * 5,
    m * 10,
    m * 15,
    m * 30,
    // day divisors (# of hrs)
    h,
    h * 2,
    h * 3,
    h * 4,
    h * 6,
    h * 8,
    h * 12,
    // month divisors TODO: need more?
    d,
    d * 2,
    d * 3,
    d * 4,
    d * 5,
    d * 6,
    d * 7,
    d * 8,
    d * 9,
    d * 10,
    d * 15,
    // year divisors (# months, approx)
    mo,
    mo * 2,
    mo * 3,
    mo * 4,
    mo * 6,
    // century divisors
    y,
    y * 2,
    y * 5,
    y * 10,
    y * 25,
    y * 50,
    y * 100
  ]);
  const _timeAxisStamps = [
    //   tick incr    default          year                    month   day                   hour    min       sec   mode
    [y, yyyy, _, _, _, _, _, _, 1],
    [d * 28, "{MMM}", NLyyyy, _, _, _, _, _, 1],
    [d, md, NLyyyy, _, _, _, _, _, 1],
    [h, "{h}" + aa, NLmdyy, _, NLmd, _, _, _, 1],
    [m, hmmaa, NLmdyy, _, NLmd, _, _, _, 1],
    [s, ss, NLmdyy + " " + hmmaa, _, NLmd + " " + hmmaa, _, NLhmmaa, _, 1],
    [ms2, ss + ".{fff}", NLmdyy + " " + hmmaa, _, NLmd + " " + hmmaa, _, NLhmmaa, _, 1]
  ];
  function timeAxisSplits(tzDate2) {
    return (self, axisIdx, scaleMin, scaleMax, foundIncr, foundSpace) => {
      let splits = [];
      let isYr = foundIncr >= y;
      let isMo = foundIncr >= mo && foundIncr < y;
      let minDate = tzDate2(scaleMin);
      let minDateTs = roundDec(minDate * ms2, 3);
      let minMin = mkDate(minDate.getFullYear(), isYr ? 0 : minDate.getMonth(), isMo || isYr ? 1 : minDate.getDate());
      let minMinTs = roundDec(minMin * ms2, 3);
      if (isMo || isYr) {
        let moIncr = isMo ? foundIncr / mo : 0;
        let yrIncr = isYr ? foundIncr / y : 0;
        let split = minDateTs == minMinTs ? minDateTs : roundDec(mkDate(minMin.getFullYear() + yrIncr, minMin.getMonth() + moIncr, 1) * ms2, 3);
        let splitDate = new Date(round(split / ms2));
        let baseYear = splitDate.getFullYear();
        let baseMonth = splitDate.getMonth();
        for (let i = 0; split <= scaleMax; i++) {
          let next = mkDate(baseYear + yrIncr * i, baseMonth + moIncr * i, 1);
          let offs = next - tzDate2(roundDec(next * ms2, 3));
          split = roundDec((+next + offs) * ms2, 3);
          if (split <= scaleMax)
            splits.push(split);
        }
      } else {
        let incr0 = foundIncr >= d ? d : foundIncr;
        let tzOffset = floor(scaleMin) - floor(minDateTs);
        let split = minMinTs + tzOffset + incrRoundUp(minDateTs - minMinTs, incr0);
        splits.push(split);
        let date0 = tzDate2(split);
        let prevHour = date0.getHours() + date0.getMinutes() / m + date0.getSeconds() / h;
        let incrHours = foundIncr / h;
        let minSpace = self.axes[axisIdx]._space;
        let pctSpace = foundSpace / minSpace;
        while (1) {
          split = roundDec(split + foundIncr, ms2 == 1 ? 0 : 3);
          if (split > scaleMax)
            break;
          if (incrHours > 1) {
            let expectedHour = floor(roundDec(prevHour + incrHours, 6)) % 24;
            let splitDate = tzDate2(split);
            let actualHour = splitDate.getHours();
            let dstShift = actualHour - expectedHour;
            if (dstShift > 1)
              dstShift = -1;
            split -= dstShift * h;
            prevHour = (prevHour + incrHours) % 24;
            let prevSplit = splits[splits.length - 1];
            let pctIncr = roundDec((split - prevSplit) / foundIncr, 3);
            if (pctIncr * pctSpace >= 0.7)
              splits.push(split);
          } else
            splits.push(split);
        }
      }
      return splits;
    };
  }
  return [
    timeIncrs,
    _timeAxisStamps,
    timeAxisSplits
  ];
}
const [timeIncrsMs, _timeAxisStampsMs, timeAxisSplitsMs] = genTimeStuffs(1);
const [timeIncrsS, _timeAxisStampsS, timeAxisSplitsS] = genTimeStuffs(1e-3);
genIncrs(2, -53, 53, [1]);
function timeAxisStamps(stampCfg, fmtDate2) {
  return stampCfg.map((s) => s.map(
    (v, i) => i == 0 || i == 8 || v == null ? v : fmtDate2(i == 1 || s[8] == 0 ? v : s[1] + v)
  ));
}
function timeAxisVals(tzDate2, stamps) {
  return (self, splits, axisIdx, foundSpace, foundIncr) => {
    let s = stamps.find((s2) => foundIncr >= s2[0]) || stamps[stamps.length - 1];
    let prevYear;
    let prevMnth;
    let prevDate;
    let prevHour;
    let prevMins;
    let prevSecs;
    return splits.map((split) => {
      let date = tzDate2(split);
      let newYear = date.getFullYear();
      let newMnth = date.getMonth();
      let newDate = date.getDate();
      let newHour = date.getHours();
      let newMins = date.getMinutes();
      let newSecs = date.getSeconds();
      let stamp = newYear != prevYear && s[2] || newMnth != prevMnth && s[3] || newDate != prevDate && s[4] || newHour != prevHour && s[5] || newMins != prevMins && s[6] || newSecs != prevSecs && s[7] || s[1];
      prevYear = newYear;
      prevMnth = newMnth;
      prevDate = newDate;
      prevHour = newHour;
      prevMins = newMins;
      prevSecs = newSecs;
      return stamp(date);
    });
  };
}
function timeAxisVal(tzDate2, dateTpl) {
  let stamp = fmtDate(dateTpl);
  return (self, splits, axisIdx, foundSpace, foundIncr) => splits.map((split) => stamp(tzDate2(split)));
}
function mkDate(y, m, d) {
  return new Date(y, m, d);
}
function timeSeriesStamp(stampCfg, fmtDate2) {
  return fmtDate2(stampCfg);
}
const _timeSeriesStamp = "{YYYY}-{MM}-{DD} {h}:{mm}{aa}";
function timeSeriesVal(tzDate2, stamp) {
  return (self, val, seriesIdx, dataIdx) => dataIdx == null ? LEGEND_DISP : stamp(tzDate2(val));
}
function legendStroke(self, seriesIdx) {
  let s = self.series[seriesIdx];
  return s.width ? s.stroke(self, seriesIdx) : s.points.width ? s.points.stroke(self, seriesIdx) : null;
}
function legendFill(self, seriesIdx) {
  return self.series[seriesIdx].fill(self, seriesIdx);
}
const legendOpts = {
  show: true,
  live: true,
  isolate: false,
  mount: noop,
  markers: {
    show: true,
    width: 2,
    stroke: legendStroke,
    fill: legendFill,
    dash: "solid"
  },
  idx: null,
  idxs: null,
  values: []
};
function cursorPointShow(self, si) {
  let o = self.cursor.points;
  let pt = placeDiv();
  let size = o.size(self, si);
  setStylePx(pt, WIDTH, size);
  setStylePx(pt, HEIGHT, size);
  let mar = size / -2;
  setStylePx(pt, "marginLeft", mar);
  setStylePx(pt, "marginTop", mar);
  let width = o.width(self, si, size);
  width && setStylePx(pt, "borderWidth", width);
  return pt;
}
function cursorPointFill(self, si) {
  let sp = self.series[si].points;
  return sp._fill || sp._stroke;
}
function cursorPointStroke(self, si) {
  let sp = self.series[si].points;
  return sp._stroke || sp._fill;
}
function cursorPointSize(self, si) {
  let sp = self.series[si].points;
  return sp.size;
}
const moveTuple = [0, 0];
function cursorMove(self, mouseLeft1, mouseTop1) {
  moveTuple[0] = mouseLeft1;
  moveTuple[1] = mouseTop1;
  return moveTuple;
}
function filtBtn0(self, targ, handle, onlyTarg = true) {
  return (e) => {
    e.button == 0 && (!onlyTarg || e.target == targ) && handle(e);
  };
}
function filtTarg(self, targ, handle, onlyTarg = true) {
  return (e) => {
    (!onlyTarg || e.target == targ) && handle(e);
  };
}
const cursorOpts = {
  show: true,
  x: true,
  y: true,
  lock: false,
  move: cursorMove,
  points: {
    one: false,
    show: cursorPointShow,
    size: cursorPointSize,
    width: 0,
    stroke: cursorPointStroke,
    fill: cursorPointFill
  },
  bind: {
    mousedown: filtBtn0,
    mouseup: filtBtn0,
    click: filtBtn0,
    // legend clicks, not .u-over clicks
    dblclick: filtBtn0,
    mousemove: filtTarg,
    mouseleave: filtTarg,
    mouseenter: filtTarg
  },
  drag: {
    setScale: true,
    x: true,
    y: false,
    dist: 0,
    uni: null,
    click: (self, e) => {
      e.stopPropagation();
      e.stopImmediatePropagation();
    },
    _x: false,
    _y: false
  },
  focus: {
    dist: (self, seriesIdx, dataIdx, valPos, curPos) => valPos - curPos,
    prox: -1,
    bias: 0
  },
  hover: {
    skip: [void 0],
    prox: null,
    bias: 0
  },
  left: -10,
  top: -10,
  idx: null,
  dataIdx: null,
  idxs: null,
  event: null
};
const axisLines = {
  show: true,
  stroke: "rgba(0,0,0,0.07)",
  width: 2
  //	dash: [],
};
const grid = assign({}, axisLines, {
  filter: retArg1
});
const ticks = assign({}, grid, {
  size: 10
});
const border = assign({}, axisLines, {
  show: false
});
const font = '12px system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol", "Noto Color Emoji"';
const labelFont = "bold " + font;
const lineGap = 1.5;
const xAxisOpts = {
  show: true,
  scale: "x",
  stroke: hexBlack,
  space: 50,
  gap: 5,
  size: 50,
  labelGap: 0,
  labelSize: 30,
  labelFont,
  side: 2,
  //	class: "x-vals",
  //	incrs: timeIncrs,
  //	values: timeVals,
  //	filter: retArg1,
  grid,
  ticks,
  border,
  font,
  lineGap,
  rotate: 0
};
const numSeriesLabel = "Value";
const timeSeriesLabel = "Time";
const xSeriesOpts = {
  show: true,
  scale: "x",
  auto: false,
  sorted: 1,
  //	label: "Time",
  //	value: v => stamp(new Date(v * 1e3)),
  // internal caches
  min: inf,
  max: -inf,
  idxs: []
};
function numAxisVals(self, splits, axisIdx, foundSpace, foundIncr) {
  return splits.map((v) => v == null ? "" : fmtNum(v));
}
function numAxisSplits(self, axisIdx, scaleMin, scaleMax, foundIncr, foundSpace, forceMin) {
  let splits = [];
  let numDec = fixedDec.get(foundIncr) || 0;
  scaleMin = forceMin ? scaleMin : roundDec(incrRoundUp(scaleMin, foundIncr), numDec);
  for (let val = scaleMin; val <= scaleMax; val = roundDec(val + foundIncr, numDec))
    splits.push(Object.is(val, -0) ? 0 : val);
  return splits;
}
function logAxisSplits(self, axisIdx, scaleMin, scaleMax, foundIncr, foundSpace, forceMin) {
  const splits = [];
  const logBase = self.scales[self.axes[axisIdx].scale].log;
  const logFn = logBase == 10 ? log10 : log2;
  const exp = floor(logFn(scaleMin));
  foundIncr = pow(logBase, exp);
  if (logBase == 10)
    foundIncr = numIncrs[closestIdx(foundIncr, numIncrs)];
  let split = scaleMin;
  let nextMagIncr = foundIncr * logBase;
  if (logBase == 10)
    nextMagIncr = numIncrs[closestIdx(nextMagIncr, numIncrs)];
  do {
    splits.push(split);
    split = split + foundIncr;
    if (logBase == 10 && !fixedDec.has(split))
      split = roundDec(split, fixedDec.get(foundIncr));
    if (split >= nextMagIncr) {
      foundIncr = split;
      nextMagIncr = foundIncr * logBase;
      if (logBase == 10)
        nextMagIncr = numIncrs[closestIdx(nextMagIncr, numIncrs)];
    }
  } while (split <= scaleMax);
  return splits;
}
function asinhAxisSplits(self, axisIdx, scaleMin, scaleMax, foundIncr, foundSpace, forceMin) {
  let sc = self.scales[self.axes[axisIdx].scale];
  let linthresh = sc.asinh;
  let posSplits = scaleMax > linthresh ? logAxisSplits(self, axisIdx, max(linthresh, scaleMin), scaleMax, foundIncr) : [linthresh];
  let zero = scaleMax >= 0 && scaleMin <= 0 ? [0] : [];
  let negSplits = scaleMin < -linthresh ? logAxisSplits(self, axisIdx, max(linthresh, -scaleMax), -scaleMin, foundIncr) : [linthresh];
  return negSplits.reverse().map((v) => -v).concat(zero, posSplits);
}
const RE_ALL = /./;
const RE_12357 = /[12357]/;
const RE_125 = /[125]/;
const RE_1 = /1/;
const _filt = (splits, distr, re, keepMod) => splits.map((v, i) => distr == 4 && v == 0 || i % keepMod == 0 && re.test(v.toExponential()[v < 0 ? 1 : 0]) ? v : null);
function log10AxisValsFilt(self, splits, axisIdx, foundSpace, foundIncr) {
  let axis = self.axes[axisIdx];
  let scaleKey = axis.scale;
  let sc = self.scales[scaleKey];
  let valToPos = self.valToPos;
  let minSpace = axis._space;
  let _10 = valToPos(10, scaleKey);
  let re = valToPos(9, scaleKey) - _10 >= minSpace ? RE_ALL : valToPos(7, scaleKey) - _10 >= minSpace ? RE_12357 : valToPos(5, scaleKey) - _10 >= minSpace ? RE_125 : RE_1;
  if (re == RE_1) {
    let magSpace = abs(valToPos(1, scaleKey) - _10);
    if (magSpace < minSpace)
      return _filt(splits.slice().reverse(), sc.distr, re, ceil(minSpace / magSpace)).reverse();
  }
  return _filt(splits, sc.distr, re, 1);
}
function log2AxisValsFilt(self, splits, axisIdx, foundSpace, foundIncr) {
  let axis = self.axes[axisIdx];
  let scaleKey = axis.scale;
  let minSpace = axis._space;
  let valToPos = self.valToPos;
  let magSpace = abs(valToPos(1, scaleKey) - valToPos(2, scaleKey));
  if (magSpace < minSpace)
    return _filt(splits.slice().reverse(), 3, RE_ALL, ceil(minSpace / magSpace)).reverse();
  return splits;
}
function numSeriesVal(self, val, seriesIdx, dataIdx) {
  return dataIdx == null ? LEGEND_DISP : val == null ? "" : fmtNum(val);
}
const yAxisOpts = {
  show: true,
  scale: "y",
  stroke: hexBlack,
  space: 30,
  gap: 5,
  size: 50,
  labelGap: 0,
  labelSize: 30,
  labelFont,
  side: 3,
  //	class: "y-vals",
  //	incrs: numIncrs,
  //	values: (vals, space) => vals,
  //	filter: retArg1,
  grid,
  ticks,
  border,
  font,
  lineGap,
  rotate: 0
};
function ptDia(width, mult) {
  let dia = 3 + (width || 1) * 2;
  return roundDec(dia * mult, 3);
}
function seriesPointsShow(self, si) {
  let { scale, idxs } = self.series[0];
  let xData = self._data[0];
  let p0 = self.valToPos(xData[idxs[0]], scale, true);
  let p1 = self.valToPos(xData[idxs[1]], scale, true);
  let dim = abs(p1 - p0);
  let s = self.series[si];
  let maxPts = dim / (s.points.space * pxRatio);
  return idxs[1] - idxs[0] <= maxPts;
}
const facet = {
  scale: null,
  auto: true,
  sorted: 0,
  // internal caches
  min: inf,
  max: -inf
};
const gaps = (self, seriesIdx, idx0, idx1, nullGaps) => nullGaps;
const xySeriesOpts = {
  show: true,
  auto: true,
  sorted: 0,
  gaps,
  alpha: 1,
  facets: [
    assign({}, facet, { scale: "x" }),
    assign({}, facet, { scale: "y" })
  ]
};
const ySeriesOpts = {
  scale: "y",
  auto: true,
  sorted: 0,
  show: true,
  spanGaps: false,
  gaps,
  alpha: 1,
  points: {
    show: seriesPointsShow,
    filter: null
    //  paths:
    //	stroke: "#000",
    //	fill: "#fff",
    //	width: 1,
    //	size: 10,
  },
  //	label: "Value",
  //	value: v => v,
  values: null,
  // internal caches
  min: inf,
  max: -inf,
  idxs: [],
  path: null,
  clip: null
};
function clampScale(self, val, scaleMin, scaleMax, scaleKey) {
  return scaleMin / 10;
}
const xScaleOpts = {
  time: FEAT_TIME,
  auto: true,
  distr: 1,
  log: 10,
  asinh: 1,
  min: null,
  max: null,
  dir: 1,
  ori: 0
};
const yScaleOpts = assign({}, xScaleOpts, {
  time: false,
  ori: 1
});
const syncs = {};
function _sync(key, opts) {
  let s = syncs[key];
  if (!s) {
    s = {
      key,
      plots: [],
      sub(plot) {
        s.plots.push(plot);
      },
      unsub(plot) {
        s.plots = s.plots.filter((c) => c != plot);
      },
      pub(type, self, x, y, w, h, i) {
        for (let j = 0; j < s.plots.length; j++)
          s.plots[j] != self && s.plots[j].pub(type, self, x, y, w, h, i);
      }
    };
    if (key != null)
      syncs[key] = s;
  }
  return s;
}
const BAND_CLIP_FILL = 1 << 0;
const BAND_CLIP_STROKE = 1 << 1;
function orient(u, seriesIdx, cb) {
  const mode = u.mode;
  const series = u.series[seriesIdx];
  const data = mode == 2 ? u._data[seriesIdx] : u._data;
  const scales = u.scales;
  const bbox = u.bbox;
  let dx = data[0], dy = mode == 2 ? data[1] : data[seriesIdx], sx = mode == 2 ? scales[series.facets[0].scale] : scales[u.series[0].scale], sy = mode == 2 ? scales[series.facets[1].scale] : scales[series.scale], l = bbox.left, t = bbox.top, w = bbox.width, h = bbox.height, H = u.valToPosH, V = u.valToPosV;
  return sx.ori == 0 ? cb(
    series,
    dx,
    dy,
    sx,
    sy,
    H,
    V,
    l,
    t,
    w,
    h,
    moveToH,
    lineToH,
    rectH,
    arcH,
    bezierCurveToH
  ) : cb(
    series,
    dx,
    dy,
    sx,
    sy,
    V,
    H,
    t,
    l,
    h,
    w,
    moveToV,
    lineToV,
    rectV,
    arcV,
    bezierCurveToV
  );
}
function bandFillClipDirs(self, seriesIdx) {
  let fillDir = 0;
  let clipDirs = 0;
  let bands = ifNull(self.bands, EMPTY_ARR);
  for (let i = 0; i < bands.length; i++) {
    let b = bands[i];
    if (b.series[0] == seriesIdx)
      fillDir = b.dir;
    else if (b.series[1] == seriesIdx) {
      if (b.dir == 1)
        clipDirs |= 1;
      else
        clipDirs |= 2;
    }
  }
  return [
    fillDir,
    clipDirs == 1 ? -1 : (
      // neg only
      clipDirs == 2 ? 1 : (
        // pos only
        clipDirs == 3 ? 2 : (
          // both
          0
        )
      )
    )
  ];
}
function seriesFillTo(self, seriesIdx, dataMin, dataMax, bandFillDir) {
  let mode = self.mode;
  let series = self.series[seriesIdx];
  let scaleKey = mode == 2 ? series.facets[1].scale : series.scale;
  let scale = self.scales[scaleKey];
  return bandFillDir == -1 ? scale.min : bandFillDir == 1 ? scale.max : scale.distr == 3 ? scale.dir == 1 ? scale.min : scale.max : 0;
}
function clipBandLine(self, seriesIdx, idx0, idx1, strokePath, clipDir) {
  return orient(self, seriesIdx, (series, dataX, dataY, scaleX, scaleY, valToPosX, valToPosY, xOff, yOff, xDim, yDim) => {
    let pxRound = series.pxRound;
    const dir = scaleX.dir * (scaleX.ori == 0 ? 1 : -1);
    const lineTo = scaleX.ori == 0 ? lineToH : lineToV;
    let frIdx, toIdx;
    if (dir == 1) {
      frIdx = idx0;
      toIdx = idx1;
    } else {
      frIdx = idx1;
      toIdx = idx0;
    }
    let x0 = pxRound(valToPosX(dataX[frIdx], scaleX, xDim, xOff));
    let y0 = pxRound(valToPosY(dataY[frIdx], scaleY, yDim, yOff));
    let x1 = pxRound(valToPosX(dataX[toIdx], scaleX, xDim, xOff));
    let yLimit = pxRound(valToPosY(clipDir == 1 ? scaleY.max : scaleY.min, scaleY, yDim, yOff));
    let clip = new Path2D(strokePath);
    lineTo(clip, x1, yLimit);
    lineTo(clip, x0, yLimit);
    lineTo(clip, x0, y0);
    return clip;
  });
}
function clipGaps(gaps2, ori, plotLft, plotTop, plotWid, plotHgt) {
  let clip = null;
  if (gaps2.length > 0) {
    clip = new Path2D();
    const rect2 = ori == 0 ? rectH : rectV;
    let prevGapEnd = plotLft;
    for (let i = 0; i < gaps2.length; i++) {
      let g = gaps2[i];
      if (g[1] > g[0]) {
        let w2 = g[0] - prevGapEnd;
        w2 > 0 && rect2(clip, prevGapEnd, plotTop, w2, plotTop + plotHgt);
        prevGapEnd = g[1];
      }
    }
    let w = plotLft + plotWid - prevGapEnd;
    let maxStrokeWidth = 10;
    w > 0 && rect2(clip, prevGapEnd, plotTop - maxStrokeWidth / 2, w, plotTop + plotHgt + maxStrokeWidth);
  }
  return clip;
}
function addGap(gaps2, fromX, toX) {
  let prevGap = gaps2[gaps2.length - 1];
  if (prevGap && prevGap[0] == fromX)
    prevGap[1] = toX;
  else
    gaps2.push([fromX, toX]);
}
function findGaps(xs, ys, idx0, idx1, dir, pixelForX, align) {
  let gaps2 = [];
  let len = xs.length;
  for (let i = dir == 1 ? idx0 : idx1; i >= idx0 && i <= idx1; i += dir) {
    let yVal = ys[i];
    if (yVal === null) {
      let fr = i, to = i;
      if (dir == 1) {
        while (++i <= idx1 && ys[i] === null)
          to = i;
      } else {
        while (--i >= idx0 && ys[i] === null)
          to = i;
      }
      let frPx = pixelForX(xs[fr]);
      let toPx = to == fr ? frPx : pixelForX(xs[to]);
      let fri2 = fr - dir;
      let frPx2 = align <= 0 && fri2 >= 0 && fri2 < len ? pixelForX(xs[fri2]) : frPx;
      frPx = frPx2;
      let toi2 = to + dir;
      let toPx2 = align >= 0 && toi2 >= 0 && toi2 < len ? pixelForX(xs[toi2]) : toPx;
      toPx = toPx2;
      if (toPx >= frPx)
        gaps2.push([frPx, toPx]);
    }
  }
  return gaps2;
}
function pxRoundGen(pxAlign) {
  return pxAlign == 0 ? retArg0 : pxAlign == 1 ? round : (v) => incrRound(v, pxAlign);
}
function rect(ori) {
  let moveTo = ori == 0 ? moveToH : moveToV;
  let arcTo = ori == 0 ? (p, x1, y1, x2, y2, r) => {
    p.arcTo(x1, y1, x2, y2, r);
  } : (p, y1, x1, y2, x2, r) => {
    p.arcTo(x1, y1, x2, y2, r);
  };
  let rect2 = ori == 0 ? (p, x, y, w, h) => {
    p.rect(x, y, w, h);
  } : (p, y, x, h, w) => {
    p.rect(x, y, w, h);
  };
  return (p, x, y, w, h, endRad = 0, baseRad = 0) => {
    if (endRad == 0 && baseRad == 0)
      rect2(p, x, y, w, h);
    else {
      endRad = min(endRad, w / 2, h / 2);
      baseRad = min(baseRad, w / 2, h / 2);
      moveTo(p, x + endRad, y);
      arcTo(p, x + w, y, x + w, y + h, endRad);
      arcTo(p, x + w, y + h, x, y + h, baseRad);
      arcTo(p, x, y + h, x, y, baseRad);
      arcTo(p, x, y, x + w, y, endRad);
      p.closePath();
    }
  };
}
const moveToH = (p, x, y) => {
  p.moveTo(x, y);
};
const moveToV = (p, y, x) => {
  p.moveTo(x, y);
};
const lineToH = (p, x, y) => {
  p.lineTo(x, y);
};
const lineToV = (p, y, x) => {
  p.lineTo(x, y);
};
const rectH = rect(0);
const rectV = rect(1);
const arcH = (p, x, y, r, startAngle, endAngle) => {
  p.arc(x, y, r, startAngle, endAngle);
};
const arcV = (p, y, x, r, startAngle, endAngle) => {
  p.arc(x, y, r, startAngle, endAngle);
};
const bezierCurveToH = (p, bp1x, bp1y, bp2x, bp2y, p2x, p2y) => {
  p.bezierCurveTo(bp1x, bp1y, bp2x, bp2y, p2x, p2y);
};
const bezierCurveToV = (p, bp1y, bp1x, bp2y, bp2x, p2y, p2x) => {
  p.bezierCurveTo(bp1x, bp1y, bp2x, bp2y, p2x, p2y);
};
function points(opts) {
  return (u, seriesIdx, idx0, idx1, filtIdxs) => {
    return orient(u, seriesIdx, (series, dataX, dataY, scaleX, scaleY, valToPosX, valToPosY, xOff, yOff, xDim, yDim) => {
      let { pxRound, points: points2 } = series;
      let moveTo, arc;
      if (scaleX.ori == 0) {
        moveTo = moveToH;
        arc = arcH;
      } else {
        moveTo = moveToV;
        arc = arcV;
      }
      const width = roundDec(points2.width * pxRatio, 3);
      let rad = (points2.size - points2.width) / 2 * pxRatio;
      let dia = roundDec(rad * 2, 3);
      let fill = new Path2D();
      let clip = new Path2D();
      let { left: lft, top, width: wid, height: hgt } = u.bbox;
      rectH(
        clip,
        lft - dia,
        top - dia,
        wid + dia * 2,
        hgt + dia * 2
      );
      const drawPoint = (pi) => {
        if (dataY[pi] != null) {
          let x = pxRound(valToPosX(dataX[pi], scaleX, xDim, xOff));
          let y = pxRound(valToPosY(dataY[pi], scaleY, yDim, yOff));
          moveTo(fill, x + rad, y);
          arc(fill, x, y, rad, 0, PI * 2);
        }
      };
      if (filtIdxs)
        filtIdxs.forEach(drawPoint);
      else {
        for (let pi = idx0; pi <= idx1; pi++)
          drawPoint(pi);
      }
      return {
        stroke: width > 0 ? fill : null,
        fill,
        clip,
        flags: BAND_CLIP_FILL | BAND_CLIP_STROKE
      };
    });
  };
}
function _drawAcc(lineTo) {
  return (stroke, accX, minY, maxY, inY, outY) => {
    if (minY != maxY) {
      if (inY != minY && outY != minY)
        lineTo(stroke, accX, minY);
      if (inY != maxY && outY != maxY)
        lineTo(stroke, accX, maxY);
      lineTo(stroke, accX, outY);
    }
  };
}
const drawAccH = _drawAcc(lineToH);
const drawAccV = _drawAcc(lineToV);
function linear(opts) {
  const alignGaps = ifNull(opts == null ? void 0 : opts.alignGaps, 0);
  return (u, seriesIdx, idx0, idx1) => {
    return orient(u, seriesIdx, (series, dataX, dataY, scaleX, scaleY, valToPosX, valToPosY, xOff, yOff, xDim, yDim) => {
      let pxRound = series.pxRound;
      let pixelForX = (val) => pxRound(valToPosX(val, scaleX, xDim, xOff));
      let pixelForY = (val) => pxRound(valToPosY(val, scaleY, yDim, yOff));
      let lineTo, drawAcc;
      if (scaleX.ori == 0) {
        lineTo = lineToH;
        drawAcc = drawAccH;
      } else {
        lineTo = lineToV;
        drawAcc = drawAccV;
      }
      const dir = scaleX.dir * (scaleX.ori == 0 ? 1 : -1);
      const _paths = { stroke: new Path2D(), fill: null, clip: null, band: null, gaps: null, flags: BAND_CLIP_FILL };
      const stroke = _paths.stroke;
      let minY = inf, maxY = -inf, inY, outY, drawnAtX;
      let accX = pixelForX(dataX[dir == 1 ? idx0 : idx1]);
      let lftIdx = nonNullIdx(dataY, idx0, idx1, 1 * dir);
      let rgtIdx = nonNullIdx(dataY, idx0, idx1, -1 * dir);
      let lftX = pixelForX(dataX[lftIdx]);
      let rgtX = pixelForX(dataX[rgtIdx]);
      let hasGap = false;
      for (let i = dir == 1 ? idx0 : idx1; i >= idx0 && i <= idx1; i += dir) {
        let x = pixelForX(dataX[i]);
        let yVal = dataY[i];
        if (x == accX) {
          if (yVal != null) {
            outY = pixelForY(yVal);
            if (minY == inf) {
              lineTo(stroke, x, outY);
              inY = outY;
            }
            minY = min(outY, minY);
            maxY = max(outY, maxY);
          } else {
            if (yVal === null)
              hasGap = true;
          }
        } else {
          if (minY != inf) {
            drawAcc(stroke, accX, minY, maxY, inY, outY);
            drawnAtX = accX;
          }
          if (yVal != null) {
            outY = pixelForY(yVal);
            lineTo(stroke, x, outY);
            minY = maxY = inY = outY;
          } else {
            minY = inf;
            maxY = -inf;
            if (yVal === null)
              hasGap = true;
          }
          accX = x;
        }
      }
      if (minY != inf && minY != maxY && drawnAtX != accX)
        drawAcc(stroke, accX, minY, maxY, inY, outY);
      let [bandFillDir, bandClipDir] = bandFillClipDirs(u, seriesIdx);
      if (series.fill != null || bandFillDir != 0) {
        let fill = _paths.fill = new Path2D(stroke);
        let fillToVal = series.fillTo(u, seriesIdx, series.min, series.max, bandFillDir);
        let fillToY = pixelForY(fillToVal);
        lineTo(fill, rgtX, fillToY);
        lineTo(fill, lftX, fillToY);
      }
      if (!series.spanGaps) {
        let gaps2 = [];
        hasGap && gaps2.push(...findGaps(dataX, dataY, idx0, idx1, dir, pixelForX, alignGaps));
        _paths.gaps = gaps2 = series.gaps(u, seriesIdx, idx0, idx1, gaps2);
        _paths.clip = clipGaps(gaps2, scaleX.ori, xOff, yOff, xDim, yDim);
      }
      if (bandClipDir != 0) {
        _paths.band = bandClipDir == 2 ? [
          clipBandLine(u, seriesIdx, idx0, idx1, stroke, -1),
          clipBandLine(u, seriesIdx, idx0, idx1, stroke, 1)
        ] : clipBandLine(u, seriesIdx, idx0, idx1, stroke, bandClipDir);
      }
      return _paths;
    });
  };
}
function stepped(opts) {
  const align = ifNull(opts.align, 1);
  const ascDesc = ifNull(opts.ascDesc, false);
  const alignGaps = ifNull(opts.alignGaps, 0);
  const extend = ifNull(opts.extend, false);
  return (u, seriesIdx, idx0, idx1) => {
    return orient(u, seriesIdx, (series, dataX, dataY, scaleX, scaleY, valToPosX, valToPosY, xOff, yOff, xDim, yDim) => {
      let pxRound = series.pxRound;
      let { left, width } = u.bbox;
      let pixelForX = (val) => pxRound(valToPosX(val, scaleX, xDim, xOff));
      let pixelForY = (val) => pxRound(valToPosY(val, scaleY, yDim, yOff));
      let lineTo = scaleX.ori == 0 ? lineToH : lineToV;
      const _paths = { stroke: new Path2D(), fill: null, clip: null, band: null, gaps: null, flags: BAND_CLIP_FILL };
      const stroke = _paths.stroke;
      const dir = scaleX.dir * (scaleX.ori == 0 ? 1 : -1);
      idx0 = nonNullIdx(dataY, idx0, idx1, 1);
      idx1 = nonNullIdx(dataY, idx0, idx1, -1);
      let prevYPos = pixelForY(dataY[dir == 1 ? idx0 : idx1]);
      let firstXPos = pixelForX(dataX[dir == 1 ? idx0 : idx1]);
      let prevXPos = firstXPos;
      let firstXPosExt = firstXPos;
      if (extend && align == -1) {
        firstXPosExt = left;
        lineTo(stroke, firstXPosExt, prevYPos);
      }
      lineTo(stroke, firstXPos, prevYPos);
      for (let i = dir == 1 ? idx0 : idx1; i >= idx0 && i <= idx1; i += dir) {
        let yVal1 = dataY[i];
        if (yVal1 == null)
          continue;
        let x1 = pixelForX(dataX[i]);
        let y1 = pixelForY(yVal1);
        if (align == 1)
          lineTo(stroke, x1, prevYPos);
        else
          lineTo(stroke, prevXPos, y1);
        lineTo(stroke, x1, y1);
        prevYPos = y1;
        prevXPos = x1;
      }
      let prevXPosExt = prevXPos;
      if (extend && align == 1) {
        prevXPosExt = left + width;
        lineTo(stroke, prevXPosExt, prevYPos);
      }
      let [bandFillDir, bandClipDir] = bandFillClipDirs(u, seriesIdx);
      if (series.fill != null || bandFillDir != 0) {
        let fill = _paths.fill = new Path2D(stroke);
        let fillTo = series.fillTo(u, seriesIdx, series.min, series.max, bandFillDir);
        let fillToY = pixelForY(fillTo);
        lineTo(fill, prevXPosExt, fillToY);
        lineTo(fill, firstXPosExt, fillToY);
      }
      if (!series.spanGaps) {
        let gaps2 = [];
        gaps2.push(...findGaps(dataX, dataY, idx0, idx1, dir, pixelForX, alignGaps));
        let halfStroke = series.width * pxRatio / 2;
        let startsOffset = ascDesc || align == 1 ? halfStroke : -halfStroke;
        let endsOffset = ascDesc || align == -1 ? -halfStroke : halfStroke;
        gaps2.forEach((g) => {
          g[0] += startsOffset;
          g[1] += endsOffset;
        });
        _paths.gaps = gaps2 = series.gaps(u, seriesIdx, idx0, idx1, gaps2);
        _paths.clip = clipGaps(gaps2, scaleX.ori, xOff, yOff, xDim, yDim);
      }
      if (bandClipDir != 0) {
        _paths.band = bandClipDir == 2 ? [
          clipBandLine(u, seriesIdx, idx0, idx1, stroke, -1),
          clipBandLine(u, seriesIdx, idx0, idx1, stroke, 1)
        ] : clipBandLine(u, seriesIdx, idx0, idx1, stroke, bandClipDir);
      }
      return _paths;
    });
  };
}
function findColWidth(dataX, dataY, valToPosX, scaleX, xDim, xOff, colWid = inf) {
  if (dataX.length > 1) {
    let prevIdx = null;
    for (let i = 0, minDelta = Infinity; i < dataX.length; i++) {
      if (dataY[i] !== void 0) {
        if (prevIdx != null) {
          let delta = abs(dataX[i] - dataX[prevIdx]);
          if (delta < minDelta) {
            minDelta = delta;
            colWid = abs(valToPosX(dataX[i], scaleX, xDim, xOff) - valToPosX(dataX[prevIdx], scaleX, xDim, xOff));
          }
        }
        prevIdx = i;
      }
    }
  }
  return colWid;
}
function bars(opts) {
  opts = opts || EMPTY_OBJ;
  const size = ifNull(opts.size, [0.6, inf, 1]);
  const align = opts.align || 0;
  const _extraGap = opts.gap || 0;
  let ro = opts.radius;
  ro = // [valueRadius, baselineRadius]
  ro == null ? [0, 0] : typeof ro == "number" ? [ro, 0] : ro;
  const radiusFn = fnOrSelf(ro);
  const gapFactor = 1 - size[0];
  const _maxWidth = ifNull(size[1], inf);
  const _minWidth = ifNull(size[2], 1);
  const disp = ifNull(opts.disp, EMPTY_OBJ);
  const _each = ifNull(opts.each, (_2) => {
  });
  const { fill: dispFills, stroke: dispStrokes } = disp;
  return (u, seriesIdx, idx0, idx1) => {
    return orient(u, seriesIdx, (series, dataX, dataY, scaleX, scaleY, valToPosX, valToPosY, xOff, yOff, xDim, yDim) => {
      let pxRound = series.pxRound;
      let _align = align;
      let extraGap = _extraGap * pxRatio;
      let maxWidth = _maxWidth * pxRatio;
      let minWidth = _minWidth * pxRatio;
      let valRadius, baseRadius;
      if (scaleX.ori == 0)
        [valRadius, baseRadius] = radiusFn(u, seriesIdx);
      else
        [baseRadius, valRadius] = radiusFn(u, seriesIdx);
      const _dirX = scaleX.dir * (scaleX.ori == 0 ? 1 : -1);
      let rect2 = scaleX.ori == 0 ? rectH : rectV;
      let each = scaleX.ori == 0 ? _each : (u2, seriesIdx2, i, top, lft, hgt, wid) => {
        _each(u2, seriesIdx2, i, lft, top, wid, hgt);
      };
      let band = ifNull(u.bands, EMPTY_ARR).find((b) => b.series[0] == seriesIdx);
      let fillDir = band != null ? band.dir : 0;
      let fillTo = series.fillTo(u, seriesIdx, series.min, series.max, fillDir);
      let fillToY = pxRound(valToPosY(fillTo, scaleY, yDim, yOff));
      let xShift, barWid, fullGap, colWid = xDim;
      let strokeWidth = pxRound(series.width * pxRatio);
      let multiPath = false;
      let fillColors = null;
      let fillPaths = null;
      let strokeColors = null;
      let strokePaths = null;
      if (dispFills != null && (strokeWidth == 0 || dispStrokes != null)) {
        multiPath = true;
        fillColors = dispFills.values(u, seriesIdx, idx0, idx1);
        fillPaths = /* @__PURE__ */ new Map();
        new Set(fillColors).forEach((color) => {
          if (color != null)
            fillPaths.set(color, new Path2D());
        });
        if (strokeWidth > 0) {
          strokeColors = dispStrokes.values(u, seriesIdx, idx0, idx1);
          strokePaths = /* @__PURE__ */ new Map();
          new Set(strokeColors).forEach((color) => {
            if (color != null)
              strokePaths.set(color, new Path2D());
          });
        }
      }
      let { x0, size: size2 } = disp;
      if (x0 != null && size2 != null) {
        _align = 1;
        dataX = x0.values(u, seriesIdx, idx0, idx1);
        if (x0.unit == 2)
          dataX = dataX.map((pct) => u.posToVal(xOff + pct * xDim, scaleX.key, true));
        let sizes = size2.values(u, seriesIdx, idx0, idx1);
        if (size2.unit == 2)
          barWid = sizes[0] * xDim;
        else
          barWid = valToPosX(sizes[0], scaleX, xDim, xOff) - valToPosX(0, scaleX, xDim, xOff);
        colWid = findColWidth(dataX, dataY, valToPosX, scaleX, xDim, xOff, colWid);
        let gapWid = colWid - barWid;
        fullGap = gapWid + extraGap;
      } else {
        colWid = findColWidth(dataX, dataY, valToPosX, scaleX, xDim, xOff, colWid);
        let gapWid = colWid * gapFactor;
        fullGap = gapWid + extraGap;
        barWid = colWid - fullGap;
      }
      if (fullGap < 1)
        fullGap = 0;
      if (strokeWidth >= barWid / 2)
        strokeWidth = 0;
      if (fullGap < 5)
        pxRound = retArg0;
      let insetStroke = fullGap > 0;
      let rawBarWid = colWid - fullGap - (insetStroke ? strokeWidth : 0);
      barWid = pxRound(clamp(rawBarWid, minWidth, maxWidth));
      xShift = (_align == 0 ? barWid / 2 : _align == _dirX ? 0 : barWid) - _align * _dirX * ((_align == 0 ? extraGap / 2 : 0) + (insetStroke ? strokeWidth / 2 : 0));
      const _paths = { stroke: null, fill: null, clip: null, band: null, gaps: null, flags: 0 };
      const stroke = multiPath ? null : new Path2D();
      let dataY0 = null;
      if (band != null)
        dataY0 = u.data[band.series[1]];
      else {
        let { y0, y1 } = disp;
        if (y0 != null && y1 != null) {
          dataY = y1.values(u, seriesIdx, idx0, idx1);
          dataY0 = y0.values(u, seriesIdx, idx0, idx1);
        }
      }
      let radVal = valRadius * barWid;
      let radBase = baseRadius * barWid;
      for (let i = _dirX == 1 ? idx0 : idx1; i >= idx0 && i <= idx1; i += _dirX) {
        let yVal = dataY[i];
        if (yVal == null)
          continue;
        if (dataY0 != null) {
          let yVal0 = dataY0[i] ?? 0;
          if (yVal - yVal0 == 0)
            continue;
          fillToY = valToPosY(yVal0, scaleY, yDim, yOff);
        }
        let xVal = scaleX.distr != 2 || disp != null ? dataX[i] : i;
        let xPos = valToPosX(xVal, scaleX, xDim, xOff);
        let yPos = valToPosY(ifNull(yVal, fillTo), scaleY, yDim, yOff);
        let lft = pxRound(xPos - xShift);
        let btm = pxRound(max(yPos, fillToY));
        let top = pxRound(min(yPos, fillToY));
        let barHgt = btm - top;
        if (yVal != null) {
          let rv = yVal < 0 ? radBase : radVal;
          let rb = yVal < 0 ? radVal : radBase;
          if (multiPath) {
            if (strokeWidth > 0 && strokeColors[i] != null)
              rect2(strokePaths.get(strokeColors[i]), lft, top + floor(strokeWidth / 2), barWid, max(0, barHgt - strokeWidth), rv, rb);
            if (fillColors[i] != null)
              rect2(fillPaths.get(fillColors[i]), lft, top + floor(strokeWidth / 2), barWid, max(0, barHgt - strokeWidth), rv, rb);
          } else
            rect2(stroke, lft, top + floor(strokeWidth / 2), barWid, max(0, barHgt - strokeWidth), rv, rb);
          each(
            u,
            seriesIdx,
            i,
            lft - strokeWidth / 2,
            top,
            barWid + strokeWidth,
            barHgt
          );
        }
      }
      if (strokeWidth > 0)
        _paths.stroke = multiPath ? strokePaths : stroke;
      else if (!multiPath) {
        _paths._fill = series.width == 0 ? series._fill : series._stroke ?? series._fill;
        _paths.width = 0;
      }
      _paths.fill = multiPath ? fillPaths : stroke;
      return _paths;
    });
  };
}
function splineInterp(interp, opts) {
  const alignGaps = ifNull(opts == null ? void 0 : opts.alignGaps, 0);
  return (u, seriesIdx, idx0, idx1) => {
    return orient(u, seriesIdx, (series, dataX, dataY, scaleX, scaleY, valToPosX, valToPosY, xOff, yOff, xDim, yDim) => {
      let pxRound = series.pxRound;
      let pixelForX = (val) => pxRound(valToPosX(val, scaleX, xDim, xOff));
      let pixelForY = (val) => pxRound(valToPosY(val, scaleY, yDim, yOff));
      let moveTo, bezierCurveTo, lineTo;
      if (scaleX.ori == 0) {
        moveTo = moveToH;
        lineTo = lineToH;
        bezierCurveTo = bezierCurveToH;
      } else {
        moveTo = moveToV;
        lineTo = lineToV;
        bezierCurveTo = bezierCurveToV;
      }
      const dir = scaleX.dir * (scaleX.ori == 0 ? 1 : -1);
      idx0 = nonNullIdx(dataY, idx0, idx1, 1);
      idx1 = nonNullIdx(dataY, idx0, idx1, -1);
      let firstXPos = pixelForX(dataX[dir == 1 ? idx0 : idx1]);
      let prevXPos = firstXPos;
      let xCoords = [];
      let yCoords = [];
      for (let i = dir == 1 ? idx0 : idx1; i >= idx0 && i <= idx1; i += dir) {
        let yVal = dataY[i];
        if (yVal != null) {
          let xVal = dataX[i];
          let xPos = pixelForX(xVal);
          xCoords.push(prevXPos = xPos);
          yCoords.push(pixelForY(dataY[i]));
        }
      }
      const _paths = { stroke: interp(xCoords, yCoords, moveTo, lineTo, bezierCurveTo, pxRound), fill: null, clip: null, band: null, gaps: null, flags: BAND_CLIP_FILL };
      const stroke = _paths.stroke;
      let [bandFillDir, bandClipDir] = bandFillClipDirs(u, seriesIdx);
      if (series.fill != null || bandFillDir != 0) {
        let fill = _paths.fill = new Path2D(stroke);
        let fillTo = series.fillTo(u, seriesIdx, series.min, series.max, bandFillDir);
        let fillToY = pixelForY(fillTo);
        lineTo(fill, prevXPos, fillToY);
        lineTo(fill, firstXPos, fillToY);
      }
      if (!series.spanGaps) {
        let gaps2 = [];
        gaps2.push(...findGaps(dataX, dataY, idx0, idx1, dir, pixelForX, alignGaps));
        _paths.gaps = gaps2 = series.gaps(u, seriesIdx, idx0, idx1, gaps2);
        _paths.clip = clipGaps(gaps2, scaleX.ori, xOff, yOff, xDim, yDim);
      }
      if (bandClipDir != 0) {
        _paths.band = bandClipDir == 2 ? [
          clipBandLine(u, seriesIdx, idx0, idx1, stroke, -1),
          clipBandLine(u, seriesIdx, idx0, idx1, stroke, 1)
        ] : clipBandLine(u, seriesIdx, idx0, idx1, stroke, bandClipDir);
      }
      return _paths;
    });
  };
}
function monotoneCubic(opts) {
  return splineInterp(_monotoneCubic, opts);
}
function _monotoneCubic(xs, ys, moveTo, lineTo, bezierCurveTo, pxRound) {
  const n = xs.length;
  if (n < 2)
    return null;
  const path = new Path2D();
  moveTo(path, xs[0], ys[0]);
  if (n == 2)
    lineTo(path, xs[1], ys[1]);
  else {
    let ms2 = Array(n), ds = Array(n - 1), dys = Array(n - 1), dxs = Array(n - 1);
    for (let i = 0; i < n - 1; i++) {
      dys[i] = ys[i + 1] - ys[i];
      dxs[i] = xs[i + 1] - xs[i];
      ds[i] = dys[i] / dxs[i];
    }
    ms2[0] = ds[0];
    for (let i = 1; i < n - 1; i++) {
      if (ds[i] === 0 || ds[i - 1] === 0 || ds[i - 1] > 0 !== ds[i] > 0)
        ms2[i] = 0;
      else {
        ms2[i] = 3 * (dxs[i - 1] + dxs[i]) / ((2 * dxs[i] + dxs[i - 1]) / ds[i - 1] + (dxs[i] + 2 * dxs[i - 1]) / ds[i]);
        if (!isFinite(ms2[i]))
          ms2[i] = 0;
      }
    }
    ms2[n - 1] = ds[n - 2];
    for (let i = 0; i < n - 1; i++) {
      bezierCurveTo(
        path,
        xs[i] + dxs[i] / 3,
        ys[i] + ms2[i] * dxs[i] / 3,
        xs[i + 1] - dxs[i] / 3,
        ys[i + 1] - ms2[i + 1] * dxs[i] / 3,
        xs[i + 1],
        ys[i + 1]
      );
    }
  }
  return path;
}
const cursorPlots = /* @__PURE__ */ new Set();
function invalidateRects() {
  for (let u of cursorPlots)
    u.syncRect(true);
}
if (domEnv) {
  on(resize, win, invalidateRects);
  on(scroll, win, invalidateRects, true);
  on(dppxchange, win, () => {
    uPlot.pxRatio = pxRatio;
  });
}
const linearPath = linear();
const pointsPath = points();
function setDefaults(d, xo, yo, initY) {
  let d2 = initY ? [d[0], d[1]].concat(d.slice(2)) : [d[0]].concat(d.slice(1));
  return d2.map((o, i) => setDefault(o, i, xo, yo));
}
function setDefaults2(d, xyo) {
  return d.map((o, i) => i == 0 ? {} : assign({}, xyo, o));
}
function setDefault(o, i, xo, yo) {
  return assign({}, i == 0 ? xo : yo, o);
}
function snapNumX(self, dataMin, dataMax) {
  return dataMin == null ? nullNullTuple : [dataMin, dataMax];
}
const snapTimeX = snapNumX;
function snapNumY(self, dataMin, dataMax) {
  return dataMin == null ? nullNullTuple : rangeNum(dataMin, dataMax, rangePad, true);
}
function snapLogY(self, dataMin, dataMax, scale) {
  return dataMin == null ? nullNullTuple : rangeLog(dataMin, dataMax, self.scales[scale].log, false);
}
const snapLogX = snapLogY;
function snapAsinhY(self, dataMin, dataMax, scale) {
  return dataMin == null ? nullNullTuple : rangeAsinh(dataMin, dataMax, self.scales[scale].log, false);
}
const snapAsinhX = snapAsinhY;
function findIncr(minVal, maxVal, incrs, dim, minSpace) {
  let intDigits = max(numIntDigits(minVal), numIntDigits(maxVal));
  let delta = maxVal - minVal;
  let incrIdx = closestIdx(minSpace / dim * delta, incrs);
  do {
    let foundIncr = incrs[incrIdx];
    let foundSpace = dim * foundIncr / delta;
    if (foundSpace >= minSpace && intDigits + (foundIncr < 5 ? fixedDec.get(foundIncr) : 0) <= 17)
      return [foundIncr, foundSpace];
  } while (++incrIdx < incrs.length);
  return [0, 0];
}
function pxRatioFont(font2) {
  let fontSize, fontSizeCss;
  font2 = font2.replace(/(\d+)px/, (m, p1) => (fontSize = round((fontSizeCss = +p1) * pxRatio)) + "px");
  return [font2, fontSize, fontSizeCss];
}
function syncFontSize(axis) {
  if (axis.show) {
    [axis.font, axis.labelFont].forEach((f) => {
      let size = roundDec(f[2] * pxRatio, 1);
      f[0] = f[0].replace(/[0-9.]+px/, size + "px");
      f[1] = size;
    });
  }
}
function uPlot(opts, data, then) {
  const self = {
    mode: ifNull(opts.mode, 1)
  };
  const mode = self.mode;
  function getValPct(val, scale) {
    let _val = scale.distr == 3 ? log10(val > 0 ? val : scale.clamp(self, val, scale.min, scale.max, scale.key)) : scale.distr == 4 ? asinh(val, scale.asinh) : scale.distr == 100 ? scale.fwd(val) : val;
    return (_val - scale._min) / (scale._max - scale._min);
  }
  function getHPos(val, scale, dim, off2) {
    let pct = getValPct(val, scale);
    return off2 + dim * (scale.dir == -1 ? 1 - pct : pct);
  }
  function getVPos(val, scale, dim, off2) {
    let pct = getValPct(val, scale);
    return off2 + dim * (scale.dir == -1 ? pct : 1 - pct);
  }
  function getPos(val, scale, dim, off2) {
    return scale.ori == 0 ? getHPos(val, scale, dim, off2) : getVPos(val, scale, dim, off2);
  }
  self.valToPosH = getHPos;
  self.valToPosV = getVPos;
  let ready = false;
  self.status = 0;
  const root = self.root = placeDiv(UPLOT);
  if (opts.id != null)
    root.id = opts.id;
  addClass(root, opts.class);
  if (opts.title) {
    let title = placeDiv(TITLE, root);
    title.textContent = opts.title;
  }
  const can = placeTag("canvas");
  const ctx = self.ctx = can.getContext("2d");
  const wrap = placeDiv(WRAP, root);
  on("click", wrap, (e) => {
    if (e.target === over) {
      let didDrag = mouseLeft1 != mouseLeft0 || mouseTop1 != mouseTop0;
      didDrag && drag.click(self, e);
    }
  }, true);
  const under = self.under = placeDiv(UNDER, wrap);
  wrap.appendChild(can);
  const over = self.over = placeDiv(OVER, wrap);
  opts = copy(opts);
  const pxAlign = +ifNull(opts.pxAlign, 1);
  const pxRound = pxRoundGen(pxAlign);
  (opts.plugins || []).forEach((p) => {
    if (p.opts)
      opts = p.opts(self, opts) || opts;
  });
  const ms2 = opts.ms || 1e-3;
  const series = self.series = mode == 1 ? setDefaults(opts.series || [], xSeriesOpts, ySeriesOpts, false) : setDefaults2(opts.series || [null], xySeriesOpts);
  const axes = self.axes = setDefaults(opts.axes || [], xAxisOpts, yAxisOpts, true);
  const scales = self.scales = {};
  const bands = self.bands = opts.bands || [];
  bands.forEach((b) => {
    b.fill = fnOrSelf(b.fill || null);
    b.dir = ifNull(b.dir, -1);
  });
  const xScaleKey = mode == 2 ? series[1].facets[0].scale : series[0].scale;
  const drawOrderMap = {
    axes: drawAxesGrid,
    series: drawSeries
  };
  const drawOrder = (opts.drawOrder || ["axes", "series"]).map((key2) => drawOrderMap[key2]);
  function initScale(scaleKey) {
    let sc = scales[scaleKey];
    if (sc == null) {
      let scaleOpts = (opts.scales || EMPTY_OBJ)[scaleKey] || EMPTY_OBJ;
      if (scaleOpts.from != null) {
        initScale(scaleOpts.from);
        scales[scaleKey] = assign({}, scales[scaleOpts.from], scaleOpts, { key: scaleKey });
      } else {
        sc = scales[scaleKey] = assign({}, scaleKey == xScaleKey ? xScaleOpts : yScaleOpts, scaleOpts);
        sc.key = scaleKey;
        let isTime = sc.time;
        let rn = sc.range;
        let rangeIsArr = isArr(rn);
        if (scaleKey != xScaleKey || mode == 2 && !isTime) {
          if (rangeIsArr && (rn[0] == null || rn[1] == null)) {
            rn = {
              min: rn[0] == null ? autoRangePart : {
                mode: 1,
                hard: rn[0],
                soft: rn[0]
              },
              max: rn[1] == null ? autoRangePart : {
                mode: 1,
                hard: rn[1],
                soft: rn[1]
              }
            };
            rangeIsArr = false;
          }
          if (!rangeIsArr && isObj(rn)) {
            let cfg = rn;
            rn = (self2, dataMin, dataMax) => dataMin == null ? nullNullTuple : rangeNum(dataMin, dataMax, cfg);
          }
        }
        sc.range = fnOrSelf(rn || (isTime ? snapTimeX : scaleKey == xScaleKey ? sc.distr == 3 ? snapLogX : sc.distr == 4 ? snapAsinhX : snapNumX : sc.distr == 3 ? snapLogY : sc.distr == 4 ? snapAsinhY : snapNumY));
        sc.auto = fnOrSelf(rangeIsArr ? false : sc.auto);
        sc.clamp = fnOrSelf(sc.clamp || clampScale);
        sc._min = sc._max = null;
      }
    }
  }
  initScale("x");
  initScale("y");
  if (mode == 1) {
    series.forEach((s) => {
      initScale(s.scale);
    });
  }
  axes.forEach((a) => {
    initScale(a.scale);
  });
  for (let k in opts.scales)
    initScale(k);
  const scaleX = scales[xScaleKey];
  const xScaleDistr = scaleX.distr;
  let valToPosX, valToPosY;
  if (scaleX.ori == 0) {
    addClass(root, ORI_HZ);
    valToPosX = getHPos;
    valToPosY = getVPos;
  } else {
    addClass(root, ORI_VT);
    valToPosX = getVPos;
    valToPosY = getHPos;
  }
  const pendScales = {};
  for (let k in scales) {
    let sc = scales[k];
    if (sc.min != null || sc.max != null) {
      pendScales[k] = { min: sc.min, max: sc.max };
      sc.min = sc.max = null;
    }
  }
  const _tzDate = opts.tzDate || ((ts) => new Date(round(ts / ms2)));
  const _fmtDate = opts.fmtDate || fmtDate;
  const _timeAxisSplits = ms2 == 1 ? timeAxisSplitsMs(_tzDate) : timeAxisSplitsS(_tzDate);
  const _timeAxisVals = timeAxisVals(_tzDate, timeAxisStamps(ms2 == 1 ? _timeAxisStampsMs : _timeAxisStampsS, _fmtDate));
  const _timeSeriesVal = timeSeriesVal(_tzDate, timeSeriesStamp(_timeSeriesStamp, _fmtDate));
  const activeIdxs = [];
  const legend = self.legend = assign({}, legendOpts, opts.legend);
  const showLegend = legend.show;
  const markers = legend.markers;
  {
    legend.idxs = activeIdxs;
    markers.width = fnOrSelf(markers.width);
    markers.dash = fnOrSelf(markers.dash);
    markers.stroke = fnOrSelf(markers.stroke);
    markers.fill = fnOrSelf(markers.fill);
  }
  let legendTable;
  let legendHead;
  let legendBody;
  let legendRows = [];
  let legendCells = [];
  let legendCols;
  let multiValLegend = false;
  let NULL_LEGEND_VALUES = {};
  if (legend.live) {
    const getMultiVals = series[1] ? series[1].values : null;
    multiValLegend = getMultiVals != null;
    legendCols = multiValLegend ? getMultiVals(self, 1, 0) : { _: 0 };
    for (let k in legendCols)
      NULL_LEGEND_VALUES[k] = LEGEND_DISP;
  }
  if (showLegend) {
    legendTable = placeTag("table", LEGEND, root);
    legendBody = placeTag("tbody", null, legendTable);
    legend.mount(self, legendTable);
    if (multiValLegend) {
      legendHead = placeTag("thead", null, legendTable, legendBody);
      let head = placeTag("tr", null, legendHead);
      placeTag("th", null, head);
      for (var key in legendCols)
        placeTag("th", LEGEND_LABEL, head).textContent = key;
    } else {
      addClass(legendTable, LEGEND_INLINE);
      legend.live && addClass(legendTable, LEGEND_LIVE);
    }
  }
  const son = { show: true };
  const soff = { show: false };
  function initLegendRow(s, i) {
    if (i == 0 && (multiValLegend || !legend.live || mode == 2))
      return nullNullTuple;
    let cells = [];
    let row = placeTag("tr", LEGEND_SERIES, legendBody, legendBody.childNodes[i]);
    addClass(row, s.class);
    if (!s.show)
      addClass(row, OFF);
    let label = placeTag("th", null, row);
    if (markers.show) {
      let indic = placeDiv(LEGEND_MARKER, label);
      if (i > 0) {
        let width = markers.width(self, i);
        if (width)
          indic.style.border = width + "px " + markers.dash(self, i) + " " + markers.stroke(self, i);
        indic.style.background = markers.fill(self, i);
      }
    }
    let text2 = placeDiv(LEGEND_LABEL, label);
    text2.textContent = s.label;
    if (i > 0) {
      if (!markers.show)
        text2.style.color = s.width > 0 ? markers.stroke(self, i) : markers.fill(self, i);
      onMouse("click", label, (e) => {
        if (cursor._lock)
          return;
        setCursorEvent(e);
        let seriesIdx = series.indexOf(s);
        if ((e.ctrlKey || e.metaKey) != legend.isolate) {
          let isolate = series.some((s2, i2) => i2 > 0 && i2 != seriesIdx && s2.show);
          series.forEach((s2, i2) => {
            i2 > 0 && setSeries(i2, isolate ? i2 == seriesIdx ? son : soff : son, true, syncOpts.setSeries);
          });
        } else
          setSeries(seriesIdx, { show: !s.show }, true, syncOpts.setSeries);
      }, false);
      if (cursorFocus) {
        onMouse(mouseenter, label, (e) => {
          if (cursor._lock)
            return;
          setCursorEvent(e);
          setSeries(series.indexOf(s), FOCUS_TRUE, true, syncOpts.setSeries);
        }, false);
      }
    }
    for (var key2 in legendCols) {
      let v = placeTag("td", LEGEND_VALUE, row);
      v.textContent = "--";
      cells.push(v);
    }
    return [row, cells];
  }
  const mouseListeners = /* @__PURE__ */ new Map();
  function onMouse(ev, targ, fn, onlyTarg = true) {
    const targListeners = mouseListeners.get(targ) || {};
    const listener = cursor.bind[ev](self, targ, fn, onlyTarg);
    if (listener) {
      on(ev, targ, targListeners[ev] = listener);
      mouseListeners.set(targ, targListeners);
    }
  }
  function offMouse(ev, targ, fn) {
    const targListeners = mouseListeners.get(targ) || {};
    for (let k in targListeners) {
      if (ev == null || k == ev) {
        off(k, targ, targListeners[k]);
        delete targListeners[k];
      }
    }
    if (ev == null)
      mouseListeners.delete(targ);
  }
  let fullWidCss = 0;
  let fullHgtCss = 0;
  let plotWidCss = 0;
  let plotHgtCss = 0;
  let plotLftCss = 0;
  let plotTopCss = 0;
  let _plotLftCss = plotLftCss;
  let _plotTopCss = plotTopCss;
  let _plotWidCss = plotWidCss;
  let _plotHgtCss = plotHgtCss;
  let plotLft = 0;
  let plotTop = 0;
  let plotWid = 0;
  let plotHgt = 0;
  self.bbox = {};
  let shouldSetScales = false;
  let shouldSetSize = false;
  let shouldConvergeSize = false;
  let shouldSetCursor = false;
  let shouldSetSelect = false;
  let shouldSetLegend = false;
  function _setSize(width, height, force) {
    if (force || (width != self.width || height != self.height))
      calcSize(width, height);
    resetYSeries(false);
    shouldConvergeSize = true;
    shouldSetSize = true;
    commit();
  }
  function calcSize(width, height) {
    self.width = fullWidCss = plotWidCss = width;
    self.height = fullHgtCss = plotHgtCss = height;
    plotLftCss = plotTopCss = 0;
    calcPlotRect();
    calcAxesRects();
    let bb = self.bbox;
    plotLft = bb.left = incrRound(plotLftCss * pxRatio, 0.5);
    plotTop = bb.top = incrRound(plotTopCss * pxRatio, 0.5);
    plotWid = bb.width = incrRound(plotWidCss * pxRatio, 0.5);
    plotHgt = bb.height = incrRound(plotHgtCss * pxRatio, 0.5);
  }
  const CYCLE_LIMIT = 3;
  function convergeSize() {
    let converged = false;
    let cycleNum = 0;
    while (!converged) {
      cycleNum++;
      let axesConverged = axesCalc(cycleNum);
      let paddingConverged = paddingCalc(cycleNum);
      converged = cycleNum == CYCLE_LIMIT || axesConverged && paddingConverged;
      if (!converged) {
        calcSize(self.width, self.height);
        shouldSetSize = true;
      }
    }
  }
  function setSize({ width, height }) {
    _setSize(width, height);
  }
  self.setSize = setSize;
  function calcPlotRect() {
    let hasTopAxis = false;
    let hasBtmAxis = false;
    let hasRgtAxis = false;
    let hasLftAxis = false;
    axes.forEach((axis, i) => {
      if (axis.show && axis._show) {
        let { side, _size } = axis;
        let isVt = side % 2;
        let labelSize = axis.label != null ? axis.labelSize : 0;
        let fullSize = _size + labelSize;
        if (fullSize > 0) {
          if (isVt) {
            plotWidCss -= fullSize;
            if (side == 3) {
              plotLftCss += fullSize;
              hasLftAxis = true;
            } else
              hasRgtAxis = true;
          } else {
            plotHgtCss -= fullSize;
            if (side == 0) {
              plotTopCss += fullSize;
              hasTopAxis = true;
            } else
              hasBtmAxis = true;
          }
        }
      }
    });
    sidesWithAxes[0] = hasTopAxis;
    sidesWithAxes[1] = hasRgtAxis;
    sidesWithAxes[2] = hasBtmAxis;
    sidesWithAxes[3] = hasLftAxis;
    plotWidCss -= _padding[1] + _padding[3];
    plotLftCss += _padding[3];
    plotHgtCss -= _padding[2] + _padding[0];
    plotTopCss += _padding[0];
  }
  function calcAxesRects() {
    let off1 = plotLftCss + plotWidCss;
    let off2 = plotTopCss + plotHgtCss;
    let off3 = plotLftCss;
    let off0 = plotTopCss;
    function incrOffset(side, size) {
      switch (side) {
        case 1:
          off1 += size;
          return off1 - size;
        case 2:
          off2 += size;
          return off2 - size;
        case 3:
          off3 -= size;
          return off3 + size;
        case 0:
          off0 -= size;
          return off0 + size;
      }
    }
    axes.forEach((axis, i) => {
      if (axis.show && axis._show) {
        let side = axis.side;
        axis._pos = incrOffset(side, axis._size);
        if (axis.label != null)
          axis._lpos = incrOffset(side, axis.labelSize);
      }
    });
  }
  const cursor = self.cursor = assign({}, cursorOpts, { drag: { y: mode == 2 } }, opts.cursor);
  if (cursor.dataIdx == null) {
    let hov = cursor.hover;
    let skip = hov.skip = new Set(hov.skip ?? []);
    skip.add(void 0);
    let prox = hov.prox = fnOrSelf(hov.prox);
    let bias = hov.bias ?? (hov.bias = 0);
    cursor.dataIdx = (self2, seriesIdx, cursorIdx, valAtPosX) => {
      if (seriesIdx == 0)
        return cursorIdx;
      let idx2 = cursorIdx;
      let _prox = prox(self2, seriesIdx, cursorIdx, valAtPosX) ?? inf;
      let withProx = _prox >= 0 && _prox < inf;
      let xDim = scaleX.ori == 0 ? plotWidCss : plotHgtCss;
      let cursorLft = cursor.left;
      let xValues = data[0];
      let yValues = data[seriesIdx];
      if (skip.has(yValues[cursorIdx])) {
        idx2 = null;
        let nonNullLft = null, nonNullRgt = null, j;
        if (bias == 0 || bias == -1) {
          j = cursorIdx;
          while (nonNullLft == null && j-- > 0) {
            if (!skip.has(yValues[j]))
              nonNullLft = j;
          }
        }
        if (bias == 0 || bias == 1) {
          j = cursorIdx;
          while (nonNullRgt == null && j++ < yValues.length) {
            if (!skip.has(yValues[j]))
              nonNullRgt = j;
          }
        }
        if (nonNullLft != null || nonNullRgt != null) {
          if (withProx) {
            let lftPos = nonNullLft == null ? -Infinity : valToPosX(xValues[nonNullLft], scaleX, xDim, 0);
            let rgtPos = nonNullRgt == null ? Infinity : valToPosX(xValues[nonNullRgt], scaleX, xDim, 0);
            let lftDelta = cursorLft - lftPos;
            let rgtDelta = rgtPos - cursorLft;
            if (lftDelta <= rgtDelta) {
              if (lftDelta <= _prox)
                idx2 = nonNullLft;
            } else {
              if (rgtDelta <= _prox)
                idx2 = nonNullRgt;
            }
          } else {
            idx2 = nonNullRgt == null ? nonNullLft : nonNullLft == null ? nonNullRgt : cursorIdx - nonNullLft <= nonNullRgt - cursorIdx ? nonNullLft : nonNullRgt;
          }
        }
      } else if (withProx) {
        let dist = abs(cursorLft - valToPosX(xValues[cursorIdx], scaleX, xDim, 0));
        if (dist > _prox)
          idx2 = null;
      }
      return idx2;
    };
  }
  const setCursorEvent = (e) => {
    cursor.event = e;
  };
  cursor.idxs = activeIdxs;
  cursor._lock = false;
  let points2 = cursor.points;
  points2.show = fnOrSelf(points2.show);
  points2.size = fnOrSelf(points2.size);
  points2.stroke = fnOrSelf(points2.stroke);
  points2.width = fnOrSelf(points2.width);
  points2.fill = fnOrSelf(points2.fill);
  const focus = self.focus = assign({}, opts.focus || { alpha: 0.3 }, cursor.focus);
  const cursorFocus = focus.prox >= 0;
  const cursorOnePt = cursorFocus && points2.one;
  let cursorPts = [];
  let cursorPtsLft = [];
  let cursorPtsTop = [];
  function initCursorPt(s, si) {
    let pt = points2.show(self, si);
    if (pt) {
      addClass(pt, CURSOR_PT);
      addClass(pt, s.class);
      elTrans(pt, -10, -10, plotWidCss, plotHgtCss);
      over.insertBefore(pt, cursorPts[si]);
      return pt;
    }
  }
  function initSeries(s, i) {
    if (mode == 1 || i > 0) {
      let isTime = mode == 1 && scales[s.scale].time;
      let sv = s.value;
      s.value = isTime ? isStr(sv) ? timeSeriesVal(_tzDate, timeSeriesStamp(sv, _fmtDate)) : sv || _timeSeriesVal : sv || numSeriesVal;
      s.label = s.label || (isTime ? timeSeriesLabel : numSeriesLabel);
    }
    if (cursorOnePt || i > 0) {
      s.width = s.width == null ? 1 : s.width;
      s.paths = s.paths || linearPath || retNull;
      s.fillTo = fnOrSelf(s.fillTo || seriesFillTo);
      s.pxAlign = +ifNull(s.pxAlign, pxAlign);
      s.pxRound = pxRoundGen(s.pxAlign);
      s.stroke = fnOrSelf(s.stroke || null);
      s.fill = fnOrSelf(s.fill || null);
      s._stroke = s._fill = s._paths = s._focus = null;
      let _ptDia = ptDia(max(1, s.width), 1);
      let points3 = s.points = assign({}, {
        size: _ptDia,
        width: max(1, _ptDia * 0.2),
        stroke: s.stroke,
        space: _ptDia * 2,
        paths: pointsPath,
        _stroke: null,
        _fill: null
      }, s.points);
      points3.show = fnOrSelf(points3.show);
      points3.filter = fnOrSelf(points3.filter);
      points3.fill = fnOrSelf(points3.fill);
      points3.stroke = fnOrSelf(points3.stroke);
      points3.paths = fnOrSelf(points3.paths);
      points3.pxAlign = s.pxAlign;
    }
    if (showLegend) {
      let rowCells = initLegendRow(s, i);
      legendRows.splice(i, 0, rowCells[0]);
      legendCells.splice(i, 0, rowCells[1]);
      legend.values.push(null);
    }
    if (cursor.show) {
      activeIdxs.splice(i, 0, null);
      let pt = null;
      if (cursorOnePt) {
        if (i == 0)
          pt = initCursorPt(s, i);
      } else if (i > 0)
        pt = initCursorPt(s, i);
      cursorPts.splice(i, 0, pt);
      cursorPtsLft.splice(i, 0, 0);
      cursorPtsTop.splice(i, 0, 0);
    }
    fire("addSeries", i);
  }
  function addSeries(opts2, si) {
    si = si == null ? series.length : si;
    opts2 = mode == 1 ? setDefault(opts2, si, xSeriesOpts, ySeriesOpts) : setDefault(opts2, si, {}, xySeriesOpts);
    series.splice(si, 0, opts2);
    initSeries(series[si], si);
  }
  self.addSeries = addSeries;
  function delSeries(i) {
    series.splice(i, 1);
    if (showLegend) {
      legend.values.splice(i, 1);
      legendCells.splice(i, 1);
      let tr = legendRows.splice(i, 1)[0];
      offMouse(null, tr.firstChild);
      tr.remove();
    }
    if (cursor.show) {
      activeIdxs.splice(i, 1);
      cursorPts.splice(i, 1)[0].remove();
      cursorPtsLft.splice(i, 1);
      cursorPtsTop.splice(i, 1);
    }
    fire("delSeries", i);
  }
  self.delSeries = delSeries;
  const sidesWithAxes = [false, false, false, false];
  function initAxis(axis, i) {
    axis._show = axis.show;
    if (axis.show) {
      let isVt = axis.side % 2;
      let sc = scales[axis.scale];
      if (sc == null) {
        axis.scale = isVt ? series[1].scale : xScaleKey;
        sc = scales[axis.scale];
      }
      let isTime = sc.time;
      axis.size = fnOrSelf(axis.size);
      axis.space = fnOrSelf(axis.space);
      axis.rotate = fnOrSelf(axis.rotate);
      if (isArr(axis.incrs)) {
        axis.incrs.forEach((incr) => {
          !fixedDec.has(incr) && fixedDec.set(incr, guessDec(incr));
        });
      }
      axis.incrs = fnOrSelf(axis.incrs || (sc.distr == 2 ? wholeIncrs : isTime ? ms2 == 1 ? timeIncrsMs : timeIncrsS : numIncrs));
      axis.splits = fnOrSelf(axis.splits || (isTime && sc.distr == 1 ? _timeAxisSplits : sc.distr == 3 ? logAxisSplits : sc.distr == 4 ? asinhAxisSplits : numAxisSplits));
      axis.stroke = fnOrSelf(axis.stroke);
      axis.grid.stroke = fnOrSelf(axis.grid.stroke);
      axis.ticks.stroke = fnOrSelf(axis.ticks.stroke);
      axis.border.stroke = fnOrSelf(axis.border.stroke);
      let av = axis.values;
      axis.values = // static array of tick values
      isArr(av) && !isArr(av[0]) ? fnOrSelf(av) : (
        // temporal
        isTime ? (
          // config array of fmtDate string tpls
          isArr(av) ? timeAxisVals(_tzDate, timeAxisStamps(av, _fmtDate)) : (
            // fmtDate string tpl
            isStr(av) ? timeAxisVal(_tzDate, av) : av || _timeAxisVals
          )
        ) : av || numAxisVals
      );
      axis.filter = fnOrSelf(axis.filter || (sc.distr >= 3 && sc.log == 10 ? log10AxisValsFilt : sc.distr == 3 && sc.log == 2 ? log2AxisValsFilt : retArg1));
      axis.font = pxRatioFont(axis.font);
      axis.labelFont = pxRatioFont(axis.labelFont);
      axis._size = axis.size(self, null, i, 0);
      axis._space = axis._rotate = axis._incrs = axis._found = // foundIncrSpace
      axis._splits = axis._values = null;
      if (axis._size > 0) {
        sidesWithAxes[i] = true;
        axis._el = placeDiv(AXIS, wrap);
      }
    }
  }
  function autoPadSide(self2, side, sidesWithAxes2, cycleNum) {
    let [hasTopAxis, hasRgtAxis, hasBtmAxis, hasLftAxis] = sidesWithAxes2;
    let ori = side % 2;
    let size = 0;
    if (ori == 0 && (hasLftAxis || hasRgtAxis))
      size = side == 0 && !hasTopAxis || side == 2 && !hasBtmAxis ? round(xAxisOpts.size / 3) : 0;
    if (ori == 1 && (hasTopAxis || hasBtmAxis))
      size = side == 1 && !hasRgtAxis || side == 3 && !hasLftAxis ? round(yAxisOpts.size / 2) : 0;
    return size;
  }
  const padding = self.padding = (opts.padding || [autoPadSide, autoPadSide, autoPadSide, autoPadSide]).map((p) => fnOrSelf(ifNull(p, autoPadSide)));
  const _padding = self._padding = padding.map((p, i) => p(self, i, sidesWithAxes, 0));
  let dataLen;
  let i0 = null;
  let i1 = null;
  const idxs = mode == 1 ? series[0].idxs : null;
  let data0 = null;
  let viaAutoScaleX = false;
  function setData(_data, _resetScales) {
    data = _data == null ? [] : _data;
    self.data = self._data = data;
    if (mode == 2) {
      dataLen = 0;
      for (let i = 1; i < series.length; i++)
        dataLen += data[i][0].length;
    } else {
      if (data.length == 0)
        self.data = self._data = data = [[]];
      data0 = data[0];
      dataLen = data0.length;
      let scaleData = data;
      if (xScaleDistr == 2) {
        scaleData = data.slice();
        let _data0 = scaleData[0] = Array(dataLen);
        for (let i = 0; i < dataLen; i++)
          _data0[i] = i;
      }
      self._data = data = scaleData;
    }
    resetYSeries(true);
    fire("setData");
    if (xScaleDistr == 2) {
      shouldConvergeSize = true;
    }
    if (_resetScales !== false) {
      let xsc = scaleX;
      if (xsc.auto(self, viaAutoScaleX))
        autoScaleX();
      else
        _setScale(xScaleKey, xsc.min, xsc.max);
      shouldSetCursor = shouldSetCursor || cursor.left >= 0;
      shouldSetLegend = true;
      commit();
    }
  }
  self.setData = setData;
  function autoScaleX() {
    viaAutoScaleX = true;
    let _min, _max;
    if (mode == 1) {
      if (dataLen > 0) {
        i0 = idxs[0] = 0;
        i1 = idxs[1] = dataLen - 1;
        _min = data[0][i0];
        _max = data[0][i1];
        if (xScaleDistr == 2) {
          _min = i0;
          _max = i1;
        } else if (_min == _max) {
          if (xScaleDistr == 3)
            [_min, _max] = rangeLog(_min, _min, scaleX.log, false);
          else if (xScaleDistr == 4)
            [_min, _max] = rangeAsinh(_min, _min, scaleX.log, false);
          else if (scaleX.time)
            _max = _min + round(86400 / ms2);
          else
            [_min, _max] = rangeNum(_min, _max, rangePad, true);
        }
      } else {
        i0 = idxs[0] = _min = null;
        i1 = idxs[1] = _max = null;
      }
    }
    _setScale(xScaleKey, _min, _max);
  }
  let ctxStroke, ctxFill, ctxWidth, ctxDash, ctxJoin, ctxCap, ctxFont, ctxAlign, ctxBaseline;
  let ctxAlpha;
  function setCtxStyle(stroke, width, dash, cap, fill, join2) {
    stroke ?? (stroke = transparent);
    dash ?? (dash = EMPTY_ARR);
    cap ?? (cap = "butt");
    fill ?? (fill = transparent);
    join2 ?? (join2 = "round");
    if (stroke != ctxStroke)
      ctx.strokeStyle = ctxStroke = stroke;
    if (fill != ctxFill)
      ctx.fillStyle = ctxFill = fill;
    if (width != ctxWidth)
      ctx.lineWidth = ctxWidth = width;
    if (join2 != ctxJoin)
      ctx.lineJoin = ctxJoin = join2;
    if (cap != ctxCap)
      ctx.lineCap = ctxCap = cap;
    if (dash != ctxDash)
      ctx.setLineDash(ctxDash = dash);
  }
  function setFontStyle(font2, fill, align, baseline) {
    if (fill != ctxFill)
      ctx.fillStyle = ctxFill = fill;
    if (font2 != ctxFont)
      ctx.font = ctxFont = font2;
    if (align != ctxAlign)
      ctx.textAlign = ctxAlign = align;
    if (baseline != ctxBaseline)
      ctx.textBaseline = ctxBaseline = baseline;
  }
  function accScale(wsc, psc, facet2, data2, sorted = 0) {
    if (data2.length > 0 && wsc.auto(self, viaAutoScaleX) && (psc == null || psc.min == null)) {
      let _i0 = ifNull(i0, 0);
      let _i1 = ifNull(i1, data2.length - 1);
      let minMax = facet2.min == null ? wsc.distr == 3 ? getMinMaxLog(data2, _i0, _i1) : getMinMax(data2, _i0, _i1, sorted) : [facet2.min, facet2.max];
      wsc.min = min(wsc.min, facet2.min = minMax[0]);
      wsc.max = max(wsc.max, facet2.max = minMax[1]);
    }
  }
  const AUTOSCALE = { min: null, max: null };
  function setScales() {
    for (let k in scales) {
      let sc = scales[k];
      if (pendScales[k] == null && // scales that have never been set (on init)
      (sc.min == null || // or auto scales when the x scale was explicitly set
      pendScales[xScaleKey] != null && sc.auto(self, viaAutoScaleX))) {
        pendScales[k] = AUTOSCALE;
      }
    }
    for (let k in scales) {
      let sc = scales[k];
      if (pendScales[k] == null && sc.from != null && pendScales[sc.from] != null)
        pendScales[k] = AUTOSCALE;
    }
    if (pendScales[xScaleKey] != null)
      resetYSeries(true);
    let wipScales = {};
    for (let k in pendScales) {
      let psc = pendScales[k];
      if (psc != null) {
        let wsc = wipScales[k] = copy(scales[k], fastIsObj);
        if (psc.min != null)
          assign(wsc, psc);
        else if (k != xScaleKey || mode == 2) {
          if (dataLen == 0 && wsc.from == null) {
            let minMax = wsc.range(self, null, null, k);
            wsc.min = minMax[0];
            wsc.max = minMax[1];
          } else {
            wsc.min = inf;
            wsc.max = -inf;
          }
        }
      }
    }
    if (dataLen > 0) {
      series.forEach((s, i) => {
        if (mode == 1) {
          let k = s.scale;
          let psc = pendScales[k];
          if (psc == null)
            return;
          let wsc = wipScales[k];
          if (i == 0) {
            let minMax = wsc.range(self, wsc.min, wsc.max, k);
            wsc.min = minMax[0];
            wsc.max = minMax[1];
            i0 = closestIdx(wsc.min, data[0]);
            i1 = closestIdx(wsc.max, data[0]);
            if (i1 - i0 > 1) {
              if (data[0][i0] < wsc.min)
                i0++;
              if (data[0][i1] > wsc.max)
                i1--;
            }
            s.min = data0[i0];
            s.max = data0[i1];
          } else if (s.show && s.auto)
            accScale(wsc, psc, s, data[i], s.sorted);
          s.idxs[0] = i0;
          s.idxs[1] = i1;
        } else {
          if (i > 0) {
            if (s.show && s.auto) {
              let [xFacet, yFacet] = s.facets;
              let xScaleKey2 = xFacet.scale;
              let yScaleKey = yFacet.scale;
              let [xData, yData] = data[i];
              let wscx = wipScales[xScaleKey2];
              let wscy = wipScales[yScaleKey];
              wscx != null && accScale(wscx, pendScales[xScaleKey2], xFacet, xData, xFacet.sorted);
              wscy != null && accScale(wscy, pendScales[yScaleKey], yFacet, yData, yFacet.sorted);
              s.min = yFacet.min;
              s.max = yFacet.max;
            }
          }
        }
      });
      for (let k in wipScales) {
        let wsc = wipScales[k];
        let psc = pendScales[k];
        if (wsc.from == null && (psc == null || psc.min == null)) {
          let minMax = wsc.range(
            self,
            wsc.min == inf ? null : wsc.min,
            wsc.max == -inf ? null : wsc.max,
            k
          );
          wsc.min = minMax[0];
          wsc.max = minMax[1];
        }
      }
    }
    for (let k in wipScales) {
      let wsc = wipScales[k];
      if (wsc.from != null) {
        let base = wipScales[wsc.from];
        if (base.min == null)
          wsc.min = wsc.max = null;
        else {
          let minMax = wsc.range(self, base.min, base.max, k);
          wsc.min = minMax[0];
          wsc.max = minMax[1];
        }
      }
    }
    let changed = {};
    let anyChanged = false;
    for (let k in wipScales) {
      let wsc = wipScales[k];
      let sc = scales[k];
      if (sc.min != wsc.min || sc.max != wsc.max) {
        sc.min = wsc.min;
        sc.max = wsc.max;
        let distr = sc.distr;
        sc._min = distr == 3 ? log10(sc.min) : distr == 4 ? asinh(sc.min, sc.asinh) : distr == 100 ? sc.fwd(sc.min) : sc.min;
        sc._max = distr == 3 ? log10(sc.max) : distr == 4 ? asinh(sc.max, sc.asinh) : distr == 100 ? sc.fwd(sc.max) : sc.max;
        changed[k] = anyChanged = true;
      }
    }
    if (anyChanged) {
      series.forEach((s, i) => {
        if (mode == 2) {
          if (i > 0 && changed.y)
            s._paths = null;
        } else {
          if (changed[s.scale])
            s._paths = null;
        }
      });
      for (let k in changed) {
        shouldConvergeSize = true;
        fire("setScale", k);
      }
      if (cursor.show && cursor.left >= 0)
        shouldSetCursor = shouldSetLegend = true;
    }
    for (let k in pendScales)
      pendScales[k] = null;
  }
  function getOuterIdxs(ydata) {
    let _i0 = clamp(i0 - 1, 0, dataLen - 1);
    let _i1 = clamp(i1 + 1, 0, dataLen - 1);
    while (ydata[_i0] == null && _i0 > 0)
      _i0--;
    while (ydata[_i1] == null && _i1 < dataLen - 1)
      _i1++;
    return [_i0, _i1];
  }
  function drawSeries() {
    if (dataLen > 0) {
      series.forEach((s, i) => {
        if (i > 0 && s.show) {
          cacheStrokeFill(i, false);
          cacheStrokeFill(i, true);
          if (s._paths == null) {
            if (ctxAlpha != s.alpha)
              ctx.globalAlpha = ctxAlpha = s.alpha;
            let _idxs = mode == 2 ? [0, data[i][0].length - 1] : getOuterIdxs(data[i]);
            s._paths = s.paths(self, i, _idxs[0], _idxs[1]);
            if (ctxAlpha != 1)
              ctx.globalAlpha = ctxAlpha = 1;
          }
        }
      });
      series.forEach((s, i) => {
        if (i > 0 && s.show) {
          if (ctxAlpha != s.alpha)
            ctx.globalAlpha = ctxAlpha = s.alpha;
          s._paths != null && drawPath(i, false);
          {
            let _gaps = s._paths != null ? s._paths.gaps : null;
            let show = s.points.show(self, i, i0, i1, _gaps);
            let idxs2 = s.points.filter(self, i, show, _gaps);
            if (show || idxs2) {
              s.points._paths = s.points.paths(self, i, i0, i1, idxs2);
              drawPath(i, true);
            }
          }
          if (ctxAlpha != 1)
            ctx.globalAlpha = ctxAlpha = 1;
          fire("drawSeries", i);
        }
      });
    }
  }
  function cacheStrokeFill(si, _points) {
    let s = _points ? series[si].points : series[si];
    s._stroke = s.stroke(self, si);
    s._fill = s.fill(self, si);
  }
  function drawPath(si, _points) {
    let s = _points ? series[si].points : series[si];
    let {
      stroke,
      fill,
      clip: gapsClip,
      flags,
      _stroke: strokeStyle = s._stroke,
      _fill: fillStyle = s._fill,
      _width: width = s.width
    } = s._paths;
    width = roundDec(width * pxRatio, 3);
    let boundsClip = null;
    let offset = width % 2 / 2;
    if (_points && fillStyle == null)
      fillStyle = width > 0 ? "#fff" : strokeStyle;
    let _pxAlign = s.pxAlign == 1 && offset > 0;
    _pxAlign && ctx.translate(offset, offset);
    if (!_points) {
      let lft = plotLft - width / 2, top = plotTop - width / 2, wid = plotWid + width, hgt = plotHgt + width;
      boundsClip = new Path2D();
      boundsClip.rect(lft, top, wid, hgt);
    }
    if (_points)
      strokeFill(strokeStyle, width, s.dash, s.cap, fillStyle, stroke, fill, flags, gapsClip);
    else
      fillStroke(si, strokeStyle, width, s.dash, s.cap, fillStyle, stroke, fill, flags, boundsClip, gapsClip);
    _pxAlign && ctx.translate(-offset, -offset);
  }
  function fillStroke(si, strokeStyle, lineWidth, lineDash, lineCap, fillStyle, strokePath, fillPath, flags, boundsClip, gapsClip) {
    let didStrokeFill = false;
    flags != 0 && bands.forEach((b, bi) => {
      if (b.series[0] == si) {
        let lowerEdge = series[b.series[1]];
        let lowerData = data[b.series[1]];
        let bandClip = (lowerEdge._paths || EMPTY_OBJ).band;
        if (isArr(bandClip))
          bandClip = b.dir == 1 ? bandClip[0] : bandClip[1];
        let gapsClip2;
        let _fillStyle = null;
        if (lowerEdge.show && bandClip && hasData(lowerData, i0, i1)) {
          _fillStyle = b.fill(self, bi) || fillStyle;
          gapsClip2 = lowerEdge._paths.clip;
        } else
          bandClip = null;
        strokeFill(strokeStyle, lineWidth, lineDash, lineCap, _fillStyle, strokePath, fillPath, flags, boundsClip, gapsClip, gapsClip2, bandClip);
        didStrokeFill = true;
      }
    });
    if (!didStrokeFill)
      strokeFill(strokeStyle, lineWidth, lineDash, lineCap, fillStyle, strokePath, fillPath, flags, boundsClip, gapsClip);
  }
  const CLIP_FILL_STROKE = BAND_CLIP_FILL | BAND_CLIP_STROKE;
  function strokeFill(strokeStyle, lineWidth, lineDash, lineCap, fillStyle, strokePath, fillPath, flags, boundsClip, gapsClip, gapsClip2, bandClip) {
    setCtxStyle(strokeStyle, lineWidth, lineDash, lineCap, fillStyle);
    if (boundsClip || gapsClip || bandClip) {
      ctx.save();
      boundsClip && ctx.clip(boundsClip);
      gapsClip && ctx.clip(gapsClip);
    }
    if (bandClip) {
      if ((flags & CLIP_FILL_STROKE) == CLIP_FILL_STROKE) {
        ctx.clip(bandClip);
        gapsClip2 && ctx.clip(gapsClip2);
        doFill(fillStyle, fillPath);
        doStroke(strokeStyle, strokePath, lineWidth);
      } else if (flags & BAND_CLIP_STROKE) {
        doFill(fillStyle, fillPath);
        ctx.clip(bandClip);
        doStroke(strokeStyle, strokePath, lineWidth);
      } else if (flags & BAND_CLIP_FILL) {
        ctx.save();
        ctx.clip(bandClip);
        gapsClip2 && ctx.clip(gapsClip2);
        doFill(fillStyle, fillPath);
        ctx.restore();
        doStroke(strokeStyle, strokePath, lineWidth);
      }
    } else {
      doFill(fillStyle, fillPath);
      doStroke(strokeStyle, strokePath, lineWidth);
    }
    if (boundsClip || gapsClip || bandClip)
      ctx.restore();
  }
  function doStroke(strokeStyle, strokePath, lineWidth) {
    if (lineWidth > 0) {
      if (strokePath instanceof Map) {
        strokePath.forEach((strokePath2, strokeStyle2) => {
          ctx.strokeStyle = ctxStroke = strokeStyle2;
          ctx.stroke(strokePath2);
        });
      } else
        strokePath != null && strokeStyle && ctx.stroke(strokePath);
    }
  }
  function doFill(fillStyle, fillPath) {
    if (fillPath instanceof Map) {
      fillPath.forEach((fillPath2, fillStyle2) => {
        ctx.fillStyle = ctxFill = fillStyle2;
        ctx.fill(fillPath2);
      });
    } else
      fillPath != null && fillStyle && ctx.fill(fillPath);
  }
  function getIncrSpace(axisIdx, min2, max2, fullDim) {
    let axis = axes[axisIdx];
    let incrSpace;
    if (fullDim <= 0)
      incrSpace = [0, 0];
    else {
      let minSpace = axis._space = axis.space(self, axisIdx, min2, max2, fullDim);
      let incrs = axis._incrs = axis.incrs(self, axisIdx, min2, max2, fullDim, minSpace);
      incrSpace = findIncr(min2, max2, incrs, fullDim, minSpace);
    }
    return axis._found = incrSpace;
  }
  function drawOrthoLines(offs, filts, ori, side, pos0, len, width, stroke, dash, cap) {
    let offset = width % 2 / 2;
    pxAlign == 1 && ctx.translate(offset, offset);
    setCtxStyle(stroke, width, dash, cap, stroke);
    ctx.beginPath();
    let x0, y0, x1, y1, pos1 = pos0 + (side == 0 || side == 3 ? -len : len);
    if (ori == 0) {
      y0 = pos0;
      y1 = pos1;
    } else {
      x0 = pos0;
      x1 = pos1;
    }
    for (let i = 0; i < offs.length; i++) {
      if (filts[i] != null) {
        if (ori == 0)
          x0 = x1 = offs[i];
        else
          y0 = y1 = offs[i];
        ctx.moveTo(x0, y0);
        ctx.lineTo(x1, y1);
      }
    }
    ctx.stroke();
    pxAlign == 1 && ctx.translate(-offset, -offset);
  }
  function axesCalc(cycleNum) {
    let converged = true;
    axes.forEach((axis, i) => {
      if (!axis.show)
        return;
      let scale = scales[axis.scale];
      if (scale.min == null) {
        if (axis._show) {
          converged = false;
          axis._show = false;
          resetYSeries(false);
        }
        return;
      } else {
        if (!axis._show) {
          converged = false;
          axis._show = true;
          resetYSeries(false);
        }
      }
      let side = axis.side;
      let ori = side % 2;
      let { min: min2, max: max2 } = scale;
      let [_incr, _space] = getIncrSpace(i, min2, max2, ori == 0 ? plotWidCss : plotHgtCss);
      if (_space == 0)
        return;
      let forceMin = scale.distr == 2;
      let _splits = axis._splits = axis.splits(self, i, min2, max2, _incr, _space, forceMin);
      let splits = scale.distr == 2 ? _splits.map((i2) => data0[i2]) : _splits;
      let incr = scale.distr == 2 ? data0[_splits[1]] - data0[_splits[0]] : _incr;
      let values = axis._values = axis.values(self, axis.filter(self, splits, i, _space, incr), i, _space, incr);
      axis._rotate = side == 2 ? axis.rotate(self, values, i, _space) : 0;
      let oldSize = axis._size;
      axis._size = ceil(axis.size(self, values, i, cycleNum));
      if (oldSize != null && axis._size != oldSize)
        converged = false;
    });
    return converged;
  }
  function paddingCalc(cycleNum) {
    let converged = true;
    padding.forEach((p, i) => {
      let _p = p(self, i, sidesWithAxes, cycleNum);
      if (_p != _padding[i])
        converged = false;
      _padding[i] = _p;
    });
    return converged;
  }
  function drawAxesGrid() {
    for (let i = 0; i < axes.length; i++) {
      let axis = axes[i];
      if (!axis.show || !axis._show)
        continue;
      let side = axis.side;
      let ori = side % 2;
      let x, y;
      let fillStyle = axis.stroke(self, i);
      let shiftDir = side == 0 || side == 3 ? -1 : 1;
      if (axis.label) {
        let shiftAmt2 = axis.labelGap * shiftDir;
        let baseLpos = round((axis._lpos + shiftAmt2) * pxRatio);
        setFontStyle(axis.labelFont[0], fillStyle, "center", side == 2 ? TOP : BOTTOM);
        ctx.save();
        if (ori == 1) {
          x = y = 0;
          ctx.translate(
            baseLpos,
            round(plotTop + plotHgt / 2)
          );
          ctx.rotate((side == 3 ? -PI : PI) / 2);
        } else {
          x = round(plotLft + plotWid / 2);
          y = baseLpos;
        }
        ctx.fillText(axis.label, x, y);
        ctx.restore();
      }
      let [_incr, _space] = axis._found;
      if (_space == 0)
        continue;
      let scale = scales[axis.scale];
      let plotDim = ori == 0 ? plotWid : plotHgt;
      let plotOff = ori == 0 ? plotLft : plotTop;
      let axisGap = round(axis.gap * pxRatio);
      let _splits = axis._splits;
      let splits = scale.distr == 2 ? _splits.map((i2) => data0[i2]) : _splits;
      let incr = scale.distr == 2 ? data0[_splits[1]] - data0[_splits[0]] : _incr;
      let ticks2 = axis.ticks;
      let border2 = axis.border;
      let tickSize = ticks2.show ? round(ticks2.size * pxRatio) : 0;
      let angle = axis._rotate * -PI / 180;
      let basePos = pxRound(axis._pos * pxRatio);
      let shiftAmt = (tickSize + axisGap) * shiftDir;
      let finalPos = basePos + shiftAmt;
      y = ori == 0 ? finalPos : 0;
      x = ori == 1 ? finalPos : 0;
      let font2 = axis.font[0];
      let textAlign = axis.align == 1 ? LEFT : axis.align == 2 ? RIGHT : angle > 0 ? LEFT : angle < 0 ? RIGHT : ori == 0 ? "center" : side == 3 ? RIGHT : LEFT;
      let textBaseline = angle || ori == 1 ? "middle" : side == 2 ? TOP : BOTTOM;
      setFontStyle(font2, fillStyle, textAlign, textBaseline);
      let lineHeight = axis.font[1] * axis.lineGap;
      let canOffs = _splits.map((val) => pxRound(getPos(val, scale, plotDim, plotOff)));
      let _values = axis._values;
      for (let i2 = 0; i2 < _values.length; i2++) {
        let val = _values[i2];
        if (val != null) {
          if (ori == 0)
            x = canOffs[i2];
          else
            y = canOffs[i2];
          val = "" + val;
          let _parts = val.indexOf("\n") == -1 ? [val] : val.split(/\n/gm);
          for (let j = 0; j < _parts.length; j++) {
            let text2 = _parts[j];
            if (angle) {
              ctx.save();
              ctx.translate(x, y + j * lineHeight);
              ctx.rotate(angle);
              ctx.fillText(text2, 0, 0);
              ctx.restore();
            } else
              ctx.fillText(text2, x, y + j * lineHeight);
          }
        }
      }
      if (ticks2.show) {
        drawOrthoLines(
          canOffs,
          ticks2.filter(self, splits, i, _space, incr),
          ori,
          side,
          basePos,
          tickSize,
          roundDec(ticks2.width * pxRatio, 3),
          ticks2.stroke(self, i),
          ticks2.dash,
          ticks2.cap
        );
      }
      let grid2 = axis.grid;
      if (grid2.show) {
        drawOrthoLines(
          canOffs,
          grid2.filter(self, splits, i, _space, incr),
          ori,
          ori == 0 ? 2 : 1,
          ori == 0 ? plotTop : plotLft,
          ori == 0 ? plotHgt : plotWid,
          roundDec(grid2.width * pxRatio, 3),
          grid2.stroke(self, i),
          grid2.dash,
          grid2.cap
        );
      }
      if (border2.show) {
        drawOrthoLines(
          [basePos],
          [1],
          ori == 0 ? 1 : 0,
          ori == 0 ? 1 : 2,
          ori == 1 ? plotTop : plotLft,
          ori == 1 ? plotHgt : plotWid,
          roundDec(border2.width * pxRatio, 3),
          border2.stroke(self, i),
          border2.dash,
          border2.cap
        );
      }
    }
    fire("drawAxes");
  }
  function resetYSeries(minMax) {
    series.forEach((s, i) => {
      if (i > 0) {
        s._paths = null;
        if (minMax) {
          if (mode == 1) {
            s.min = null;
            s.max = null;
          } else {
            s.facets.forEach((f) => {
              f.min = null;
              f.max = null;
            });
          }
        }
      }
    });
  }
  let queuedCommit = false;
  let deferHooks = false;
  let hooksQueue = [];
  function flushHooks() {
    deferHooks = false;
    for (let i = 0; i < hooksQueue.length; i++)
      fire(...hooksQueue[i]);
    hooksQueue.length = 0;
  }
  function commit() {
    if (!queuedCommit) {
      microTask(_commit);
      queuedCommit = true;
    }
  }
  function batch(fn, _deferHooks = false) {
    queuedCommit = true;
    deferHooks = _deferHooks;
    fn(self);
    _commit();
    if (_deferHooks && hooksQueue.length > 0)
      queueMicrotask(flushHooks);
  }
  self.batch = batch;
  function _commit() {
    if (shouldSetScales) {
      setScales();
      shouldSetScales = false;
    }
    if (shouldConvergeSize) {
      convergeSize();
      shouldConvergeSize = false;
    }
    if (shouldSetSize) {
      setStylePx(under, LEFT, plotLftCss);
      setStylePx(under, TOP, plotTopCss);
      setStylePx(under, WIDTH, plotWidCss);
      setStylePx(under, HEIGHT, plotHgtCss);
      setStylePx(over, LEFT, plotLftCss);
      setStylePx(over, TOP, plotTopCss);
      setStylePx(over, WIDTH, plotWidCss);
      setStylePx(over, HEIGHT, plotHgtCss);
      setStylePx(wrap, WIDTH, fullWidCss);
      setStylePx(wrap, HEIGHT, fullHgtCss);
      can.width = round(fullWidCss * pxRatio);
      can.height = round(fullHgtCss * pxRatio);
      axes.forEach(({ _el, _show, _size, _pos, side }) => {
        if (_el != null) {
          if (_show) {
            let posOffset = side === 3 || side === 0 ? _size : 0;
            let isVt = side % 2 == 1;
            setStylePx(_el, isVt ? "left" : "top", _pos - posOffset);
            setStylePx(_el, isVt ? "width" : "height", _size);
            setStylePx(_el, isVt ? "top" : "left", isVt ? plotTopCss : plotLftCss);
            setStylePx(_el, isVt ? "height" : "width", isVt ? plotHgtCss : plotWidCss);
            remClass(_el, OFF);
          } else
            addClass(_el, OFF);
        }
      });
      ctxStroke = ctxFill = ctxWidth = ctxJoin = ctxCap = ctxFont = ctxAlign = ctxBaseline = ctxDash = null;
      ctxAlpha = 1;
      syncRect(true);
      if (plotLftCss != _plotLftCss || plotTopCss != _plotTopCss || plotWidCss != _plotWidCss || plotHgtCss != _plotHgtCss) {
        resetYSeries(false);
        let pctWid = plotWidCss / _plotWidCss;
        let pctHgt = plotHgtCss / _plotHgtCss;
        if (cursor.show && !shouldSetCursor && cursor.left >= 0) {
          cursor.left *= pctWid;
          cursor.top *= pctHgt;
          vCursor && elTrans(vCursor, round(cursor.left), 0, plotWidCss, plotHgtCss);
          hCursor && elTrans(hCursor, 0, round(cursor.top), plotWidCss, plotHgtCss);
          for (let i = 0; i < cursorPts.length; i++) {
            let pt = cursorPts[i];
            if (pt != null) {
              cursorPtsLft[i] *= pctWid;
              cursorPtsTop[i] *= pctHgt;
              elTrans(pt, ceil(cursorPtsLft[i]), ceil(cursorPtsTop[i]), plotWidCss, plotHgtCss);
            }
          }
        }
        if (select.show && !shouldSetSelect && select.left >= 0 && select.width > 0) {
          select.left *= pctWid;
          select.width *= pctWid;
          select.top *= pctHgt;
          select.height *= pctHgt;
          for (let prop in _hideProps)
            setStylePx(selectDiv, prop, select[prop]);
        }
        _plotLftCss = plotLftCss;
        _plotTopCss = plotTopCss;
        _plotWidCss = plotWidCss;
        _plotHgtCss = plotHgtCss;
      }
      fire("setSize");
      shouldSetSize = false;
    }
    if (fullWidCss > 0 && fullHgtCss > 0) {
      ctx.clearRect(0, 0, can.width, can.height);
      fire("drawClear");
      drawOrder.forEach((fn) => fn());
      fire("draw");
    }
    if (select.show && shouldSetSelect) {
      setSelect(select);
      shouldSetSelect = false;
    }
    if (cursor.show && shouldSetCursor) {
      updateCursor(null, true, false);
      shouldSetCursor = false;
    }
    if (legend.show && legend.live && shouldSetLegend) {
      setLegend();
      shouldSetLegend = false;
    }
    if (!ready) {
      ready = true;
      self.status = 1;
      fire("ready");
    }
    viaAutoScaleX = false;
    queuedCommit = false;
  }
  self.redraw = (rebuildPaths, recalcAxes) => {
    shouldConvergeSize = recalcAxes || false;
    if (rebuildPaths !== false)
      _setScale(xScaleKey, scaleX.min, scaleX.max);
    else
      commit();
  };
  function setScale(key2, opts2) {
    let sc = scales[key2];
    if (sc.from == null) {
      if (dataLen == 0) {
        let minMax = sc.range(self, opts2.min, opts2.max, key2);
        opts2.min = minMax[0];
        opts2.max = minMax[1];
      }
      if (opts2.min > opts2.max) {
        let _min = opts2.min;
        opts2.min = opts2.max;
        opts2.max = _min;
      }
      if (dataLen > 1 && opts2.min != null && opts2.max != null && opts2.max - opts2.min < 1e-16)
        return;
      if (key2 == xScaleKey) {
        if (sc.distr == 2 && dataLen > 0) {
          opts2.min = closestIdx(opts2.min, data[0]);
          opts2.max = closestIdx(opts2.max, data[0]);
          if (opts2.min == opts2.max)
            opts2.max++;
        }
      }
      pendScales[key2] = opts2;
      shouldSetScales = true;
      commit();
    }
  }
  self.setScale = setScale;
  let xCursor;
  let yCursor;
  let vCursor;
  let hCursor;
  let rawMouseLeft0;
  let rawMouseTop0;
  let mouseLeft0;
  let mouseTop0;
  let rawMouseLeft1;
  let rawMouseTop1;
  let mouseLeft1;
  let mouseTop1;
  let dragging = false;
  const drag = cursor.drag;
  let dragX = drag.x;
  let dragY = drag.y;
  if (cursor.show) {
    if (cursor.x)
      xCursor = placeDiv(CURSOR_X, over);
    if (cursor.y)
      yCursor = placeDiv(CURSOR_Y, over);
    if (scaleX.ori == 0) {
      vCursor = xCursor;
      hCursor = yCursor;
    } else {
      vCursor = yCursor;
      hCursor = xCursor;
    }
    mouseLeft1 = cursor.left;
    mouseTop1 = cursor.top;
  }
  const select = self.select = assign({
    show: true,
    over: true,
    left: 0,
    width: 0,
    top: 0,
    height: 0
  }, opts.select);
  const selectDiv = select.show ? placeDiv(SELECT, select.over ? over : under) : null;
  function setSelect(opts2, _fire) {
    if (select.show) {
      for (let prop in opts2) {
        select[prop] = opts2[prop];
        if (prop in _hideProps)
          setStylePx(selectDiv, prop, opts2[prop]);
      }
      _fire !== false && fire("setSelect");
    }
  }
  self.setSelect = setSelect;
  function toggleDOM(i, onOff) {
    let s = series[i];
    let label = showLegend ? legendRows[i] : null;
    if (s.show)
      label && remClass(label, OFF);
    else {
      label && addClass(label, OFF);
      let pt = cursorOnePt ? cursorPts[0] : cursorPts[i];
      elTrans(pt, -10, -10, plotWidCss, plotHgtCss);
    }
  }
  function _setScale(key2, min2, max2) {
    setScale(key2, { min: min2, max: max2 });
  }
  function setSeries(i, opts2, _fire, _pub) {
    if (opts2.focus != null)
      setFocus(i);
    if (opts2.show != null) {
      series.forEach((s, si) => {
        if (si > 0 && (i == si || i == null)) {
          s.show = opts2.show;
          toggleDOM(si, opts2.show);
          if (mode == 2) {
            _setScale(s.facets[0].scale, null, null);
            _setScale(s.facets[1].scale, null, null);
          } else
            _setScale(s.scale, null, null);
          commit();
        }
      });
    }
    _fire !== false && fire("setSeries", i, opts2);
    _pub && pubSync("setSeries", self, i, opts2);
  }
  self.setSeries = setSeries;
  function setBand(bi, opts2) {
    assign(bands[bi], opts2);
  }
  function addBand(opts2, bi) {
    opts2.fill = fnOrSelf(opts2.fill || null);
    opts2.dir = ifNull(opts2.dir, -1);
    bi = bi == null ? bands.length : bi;
    bands.splice(bi, 0, opts2);
  }
  function delBand(bi) {
    if (bi == null)
      bands.length = 0;
    else
      bands.splice(bi, 1);
  }
  self.addBand = addBand;
  self.setBand = setBand;
  self.delBand = delBand;
  function setAlpha(i, value) {
    series[i].alpha = value;
    if (cursor.show && cursorPts[i])
      cursorPts[i].style.opacity = value;
    if (showLegend && legendRows[i])
      legendRows[i].style.opacity = value;
  }
  let closestDist;
  let closestSeries;
  let focusedSeries;
  const FOCUS_TRUE = { focus: true };
  function setFocus(i) {
    if (i != focusedSeries) {
      let allFocused = i == null;
      let _setAlpha = focus.alpha != 1;
      series.forEach((s, i2) => {
        if (mode == 1 || i2 > 0) {
          let isFocused = allFocused || i2 == 0 || i2 == i;
          s._focus = allFocused ? null : isFocused;
          _setAlpha && setAlpha(i2, isFocused ? 1 : focus.alpha);
        }
      });
      focusedSeries = i;
      _setAlpha && commit();
    }
  }
  if (showLegend && cursorFocus) {
    onMouse(mouseleave, legendTable, (e) => {
      if (cursor._lock)
        return;
      setCursorEvent(e);
      if (focusedSeries != null)
        setSeries(null, FOCUS_TRUE, true, syncOpts.setSeries);
    });
  }
  function posToVal(pos, scale, can2) {
    let sc = scales[scale];
    if (can2)
      pos = pos / pxRatio - (sc.ori == 1 ? plotTopCss : plotLftCss);
    let dim = plotWidCss;
    if (sc.ori == 1) {
      dim = plotHgtCss;
      pos = dim - pos;
    }
    if (sc.dir == -1)
      pos = dim - pos;
    let _min = sc._min, _max = sc._max, pct = pos / dim;
    let sv = _min + (_max - _min) * pct;
    let distr = sc.distr;
    return distr == 3 ? pow(10, sv) : distr == 4 ? sinh(sv, sc.asinh) : distr == 100 ? sc.bwd(sv) : sv;
  }
  function closestIdxFromXpos(pos, can2) {
    let v = posToVal(pos, xScaleKey, can2);
    return closestIdx(v, data[0], i0, i1);
  }
  self.valToIdx = (val) => closestIdx(val, data[0]);
  self.posToIdx = closestIdxFromXpos;
  self.posToVal = posToVal;
  self.valToPos = (val, scale, can2) => scales[scale].ori == 0 ? getHPos(
    val,
    scales[scale],
    can2 ? plotWid : plotWidCss,
    can2 ? plotLft : 0
  ) : getVPos(
    val,
    scales[scale],
    can2 ? plotHgt : plotHgtCss,
    can2 ? plotTop : 0
  );
  self.setCursor = (opts2, _fire, _pub) => {
    mouseLeft1 = opts2.left;
    mouseTop1 = opts2.top;
    updateCursor(null, _fire, _pub);
  };
  function setSelH(off2, dim) {
    setStylePx(selectDiv, LEFT, select.left = off2);
    setStylePx(selectDiv, WIDTH, select.width = dim);
  }
  function setSelV(off2, dim) {
    setStylePx(selectDiv, TOP, select.top = off2);
    setStylePx(selectDiv, HEIGHT, select.height = dim);
  }
  let setSelX = scaleX.ori == 0 ? setSelH : setSelV;
  let setSelY = scaleX.ori == 1 ? setSelH : setSelV;
  function syncLegend() {
    if (showLegend && legend.live) {
      for (let i = mode == 2 ? 1 : 0; i < series.length; i++) {
        if (i == 0 && multiValLegend)
          continue;
        let vals = legend.values[i];
        let j = 0;
        for (let k in vals)
          legendCells[i][j++].firstChild.nodeValue = vals[k];
      }
    }
  }
  function setLegend(opts2, _fire) {
    if (opts2 != null) {
      if (opts2.idxs) {
        opts2.idxs.forEach((didx, sidx) => {
          activeIdxs[sidx] = didx;
        });
      } else if (!isUndef(opts2.idx))
        activeIdxs.fill(opts2.idx);
      legend.idx = activeIdxs[0];
    }
    if (showLegend && legend.live) {
      for (let sidx = 0; sidx < series.length; sidx++) {
        if (sidx > 0 || mode == 1 && !multiValLegend)
          setLegendValues(sidx, activeIdxs[sidx]);
      }
      syncLegend();
    }
    shouldSetLegend = false;
    _fire !== false && fire("setLegend");
  }
  self.setLegend = setLegend;
  function setLegendValues(sidx, idx) {
    let s = series[sidx];
    let src = sidx == 0 && xScaleDistr == 2 ? data0 : data[sidx];
    let val;
    if (multiValLegend)
      val = s.values(self, sidx, idx) ?? NULL_LEGEND_VALUES;
    else {
      val = s.value(self, idx == null ? null : src[idx], sidx, idx);
      val = val == null ? NULL_LEGEND_VALUES : { _: val };
    }
    legend.values[sidx] = val;
  }
  function updateCursor(src, _fire, _pub) {
    rawMouseLeft1 = mouseLeft1;
    rawMouseTop1 = mouseTop1;
    [mouseLeft1, mouseTop1] = cursor.move(self, mouseLeft1, mouseTop1);
    cursor.left = mouseLeft1;
    cursor.top = mouseTop1;
    if (cursor.show) {
      vCursor && elTrans(vCursor, round(mouseLeft1), 0, plotWidCss, plotHgtCss);
      hCursor && elTrans(hCursor, 0, round(mouseTop1), plotWidCss, plotHgtCss);
    }
    let idx;
    let noDataInRange = i0 > i1;
    closestDist = inf;
    closestSeries = null;
    let xDim = scaleX.ori == 0 ? plotWidCss : plotHgtCss;
    let yDim = scaleX.ori == 1 ? plotWidCss : plotHgtCss;
    if (mouseLeft1 < 0 || dataLen == 0 || noDataInRange) {
      idx = cursor.idx = null;
      for (let i = 0; i < series.length; i++) {
        let pt = cursorPts[i];
        pt != null && elTrans(pt, -10, -10, plotWidCss, plotHgtCss);
      }
      if (cursorFocus)
        setSeries(null, FOCUS_TRUE, true, src == null && syncOpts.setSeries);
      if (legend.live) {
        activeIdxs.fill(idx);
        shouldSetLegend = true;
      }
    } else {
      let mouseXPos, valAtPosX, xPos;
      if (mode == 1) {
        mouseXPos = scaleX.ori == 0 ? mouseLeft1 : mouseTop1;
        valAtPosX = posToVal(mouseXPos, xScaleKey);
        idx = cursor.idx = closestIdx(valAtPosX, data[0], i0, i1);
        xPos = valToPosX(data[0][idx], scaleX, xDim, 0);
      }
      let _ptLft = -10;
      let _ptTop = -10;
      let _ptWid = 0;
      let _ptHgt = 0;
      let _centered = true;
      let _ptFill = "";
      let _ptStroke = "";
      for (let i = mode == 2 ? 1 : 0; i < series.length; i++) {
        let s = series[i];
        let idx1 = activeIdxs[i];
        let yVal1 = idx1 == null ? null : mode == 1 ? data[i][idx1] : data[i][1][idx1];
        let idx2 = cursor.dataIdx(self, i, idx, valAtPosX);
        let yVal2 = idx2 == null ? null : mode == 1 ? data[i][idx2] : data[i][1][idx2];
        shouldSetLegend = shouldSetLegend || yVal2 != yVal1 || idx2 != idx1;
        activeIdxs[i] = idx2;
        let xPos2 = idx2 == idx ? xPos : valToPosX(mode == 1 ? data[0][idx2] : data[i][0][idx2], scaleX, xDim, 0);
        if (i > 0 && s.show) {
          let yPos = yVal2 == null ? -10 : valToPosY(yVal2, mode == 1 ? scales[s.scale] : scales[s.facets[1].scale], yDim, 0);
          if (cursorFocus && yVal2 != null) {
            let mouseYPos = scaleX.ori == 1 ? mouseLeft1 : mouseTop1;
            let dist = abs(focus.dist(self, i, idx2, yPos, mouseYPos));
            if (dist < closestDist) {
              let bias = focus.bias;
              if (bias != 0) {
                let mouseYVal = posToVal(mouseYPos, s.scale);
                let seriesYValSign = yVal2 >= 0 ? 1 : -1;
                let mouseYValSign = mouseYVal >= 0 ? 1 : -1;
                if (mouseYValSign == seriesYValSign && (mouseYValSign == 1 ? bias == 1 ? yVal2 >= mouseYVal : yVal2 <= mouseYVal : (
                  // >= 0
                  bias == 1 ? yVal2 <= mouseYVal : yVal2 >= mouseYVal
                ))) {
                  closestDist = dist;
                  closestSeries = i;
                }
              } else {
                closestDist = dist;
                closestSeries = i;
              }
            }
          }
          if (shouldSetLegend || cursorOnePt) {
            let hPos, vPos;
            if (scaleX.ori == 0) {
              hPos = xPos2;
              vPos = yPos;
            } else {
              hPos = yPos;
              vPos = xPos2;
            }
            let ptWid, ptHgt, ptLft, ptTop, ptStroke, ptFill, centered = true, getBBox = points2.bbox;
            if (getBBox != null) {
              centered = false;
              let bbox = getBBox(self, i);
              ptLft = bbox.left;
              ptTop = bbox.top;
              ptWid = bbox.width;
              ptHgt = bbox.height;
            } else {
              ptLft = hPos;
              ptTop = vPos;
              ptWid = ptHgt = points2.size(self, i);
            }
            ptFill = points2.fill(self, i);
            ptStroke = points2.stroke(self, i);
            if (cursorOnePt) {
              if (i == closestSeries && closestDist <= focus.prox) {
                _ptLft = ptLft;
                _ptTop = ptTop;
                _ptWid = ptWid;
                _ptHgt = ptHgt;
                _centered = centered;
                _ptFill = ptFill;
                _ptStroke = ptStroke;
              }
            } else {
              let pt = cursorPts[i];
              if (pt != null) {
                cursorPtsLft[i] = ptLft;
                cursorPtsTop[i] = ptTop;
                elSize(pt, ptWid, ptHgt, centered);
                elColor(pt, ptFill, ptStroke);
                elTrans(pt, ceil(ptLft), ceil(ptTop), plotWidCss, plotHgtCss);
              }
            }
          }
        }
      }
      if (cursorOnePt) {
        let p = focus.prox;
        let focusChanged = focusedSeries == null ? closestDist <= p : closestDist > p || closestSeries != focusedSeries;
        if (shouldSetLegend || focusChanged) {
          let pt = cursorPts[0];
          cursorPtsLft[0] = _ptLft;
          cursorPtsTop[0] = _ptTop;
          elSize(pt, _ptWid, _ptHgt, _centered);
          elColor(pt, _ptFill, _ptStroke);
          elTrans(pt, ceil(_ptLft), ceil(_ptTop), plotWidCss, plotHgtCss);
        }
      }
    }
    if (select.show && dragging) {
      if (src != null) {
        let [xKey, yKey] = syncOpts.scales;
        let [matchXKeys, matchYKeys] = syncOpts.match;
        let [xKeySrc, yKeySrc] = src.cursor.sync.scales;
        let sdrag = src.cursor.drag;
        dragX = sdrag._x;
        dragY = sdrag._y;
        if (dragX || dragY) {
          let { left, top, width, height } = src.select;
          let sori = src.scales[xKeySrc].ori;
          let sPosToVal = src.posToVal;
          let sOff, sDim, sc, a, b;
          let matchingX = xKey != null && matchXKeys(xKey, xKeySrc);
          let matchingY = yKey != null && matchYKeys(yKey, yKeySrc);
          if (matchingX && dragX) {
            if (sori == 0) {
              sOff = left;
              sDim = width;
            } else {
              sOff = top;
              sDim = height;
            }
            sc = scales[xKey];
            a = valToPosX(sPosToVal(sOff, xKeySrc), sc, xDim, 0);
            b = valToPosX(sPosToVal(sOff + sDim, xKeySrc), sc, xDim, 0);
            setSelX(min(a, b), abs(b - a));
          } else
            setSelX(0, xDim);
          if (matchingY && dragY) {
            if (sori == 1) {
              sOff = left;
              sDim = width;
            } else {
              sOff = top;
              sDim = height;
            }
            sc = scales[yKey];
            a = valToPosY(sPosToVal(sOff, yKeySrc), sc, yDim, 0);
            b = valToPosY(sPosToVal(sOff + sDim, yKeySrc), sc, yDim, 0);
            setSelY(min(a, b), abs(b - a));
          } else
            setSelY(0, yDim);
        } else
          hideSelect();
      } else {
        let rawDX = abs(rawMouseLeft1 - rawMouseLeft0);
        let rawDY = abs(rawMouseTop1 - rawMouseTop0);
        if (scaleX.ori == 1) {
          let _rawDX = rawDX;
          rawDX = rawDY;
          rawDY = _rawDX;
        }
        dragX = drag.x && rawDX >= drag.dist;
        dragY = drag.y && rawDY >= drag.dist;
        let uni = drag.uni;
        if (uni != null) {
          if (dragX && dragY) {
            dragX = rawDX >= uni;
            dragY = rawDY >= uni;
            if (!dragX && !dragY) {
              if (rawDY > rawDX)
                dragY = true;
              else
                dragX = true;
            }
          }
        } else if (drag.x && drag.y && (dragX || dragY))
          dragX = dragY = true;
        let p0, p1;
        if (dragX) {
          if (scaleX.ori == 0) {
            p0 = mouseLeft0;
            p1 = mouseLeft1;
          } else {
            p0 = mouseTop0;
            p1 = mouseTop1;
          }
          setSelX(min(p0, p1), abs(p1 - p0));
          if (!dragY)
            setSelY(0, yDim);
        }
        if (dragY) {
          if (scaleX.ori == 1) {
            p0 = mouseLeft0;
            p1 = mouseLeft1;
          } else {
            p0 = mouseTop0;
            p1 = mouseTop1;
          }
          setSelY(min(p0, p1), abs(p1 - p0));
          if (!dragX)
            setSelX(0, xDim);
        }
        if (!dragX && !dragY) {
          setSelX(0, 0);
          setSelY(0, 0);
        }
      }
    }
    drag._x = dragX;
    drag._y = dragY;
    if (src == null) {
      if (_pub) {
        if (syncKey != null) {
          let [xSyncKey, ySyncKey] = syncOpts.scales;
          syncOpts.values[0] = xSyncKey != null ? posToVal(scaleX.ori == 0 ? mouseLeft1 : mouseTop1, xSyncKey) : null;
          syncOpts.values[1] = ySyncKey != null ? posToVal(scaleX.ori == 1 ? mouseLeft1 : mouseTop1, ySyncKey) : null;
        }
        pubSync(mousemove, self, mouseLeft1, mouseTop1, plotWidCss, plotHgtCss, idx);
      }
      if (cursorFocus) {
        let shouldPub = _pub && syncOpts.setSeries;
        let p = focus.prox;
        if (focusedSeries == null) {
          if (closestDist <= p)
            setSeries(closestSeries, FOCUS_TRUE, true, shouldPub);
        } else {
          if (closestDist > p)
            setSeries(null, FOCUS_TRUE, true, shouldPub);
          else if (closestSeries != focusedSeries)
            setSeries(closestSeries, FOCUS_TRUE, true, shouldPub);
        }
      }
    }
    if (shouldSetLegend) {
      legend.idx = idx;
      setLegend();
    }
    _fire !== false && fire("setCursor");
  }
  let rect2 = null;
  Object.defineProperty(self, "rect", {
    get() {
      if (rect2 == null)
        syncRect(false);
      return rect2;
    }
  });
  function syncRect(defer = false) {
    if (defer)
      rect2 = null;
    else {
      rect2 = over.getBoundingClientRect();
      fire("syncRect", rect2);
    }
  }
  function mouseMove(e, src, _l, _t, _w, _h, _i) {
    if (cursor._lock)
      return;
    if (dragging && e != null && e.movementX == 0 && e.movementY == 0)
      return;
    cacheMouse(e, src, _l, _t, _w, _h, _i, false, e != null);
    if (e != null)
      updateCursor(null, true, true);
    else
      updateCursor(src, true, false);
  }
  function cacheMouse(e, src, _l, _t, _w, _h, _i, initial, snap) {
    if (rect2 == null)
      syncRect(false);
    setCursorEvent(e);
    if (e != null) {
      _l = e.clientX - rect2.left;
      _t = e.clientY - rect2.top;
    } else {
      if (_l < 0 || _t < 0) {
        mouseLeft1 = -10;
        mouseTop1 = -10;
        return;
      }
      let [xKey, yKey] = syncOpts.scales;
      let syncOptsSrc = src.cursor.sync;
      let [xValSrc, yValSrc] = syncOptsSrc.values;
      let [xKeySrc, yKeySrc] = syncOptsSrc.scales;
      let [matchXKeys, matchYKeys] = syncOpts.match;
      let rotSrc = src.axes[0].side % 2 == 1;
      let xDim = scaleX.ori == 0 ? plotWidCss : plotHgtCss, yDim = scaleX.ori == 1 ? plotWidCss : plotHgtCss, _xDim = rotSrc ? _h : _w, _yDim = rotSrc ? _w : _h, _xPos = rotSrc ? _t : _l, _yPos = rotSrc ? _l : _t;
      if (xKeySrc != null)
        _l = matchXKeys(xKey, xKeySrc) ? getPos(xValSrc, scales[xKey], xDim, 0) : -10;
      else
        _l = xDim * (_xPos / _xDim);
      if (yKeySrc != null)
        _t = matchYKeys(yKey, yKeySrc) ? getPos(yValSrc, scales[yKey], yDim, 0) : -10;
      else
        _t = yDim * (_yPos / _yDim);
      if (scaleX.ori == 1) {
        let __l = _l;
        _l = _t;
        _t = __l;
      }
    }
    if (snap) {
      if (_l <= 1 || _l >= plotWidCss - 1)
        _l = incrRound(_l, plotWidCss);
      if (_t <= 1 || _t >= plotHgtCss - 1)
        _t = incrRound(_t, plotHgtCss);
    }
    if (initial) {
      rawMouseLeft0 = _l;
      rawMouseTop0 = _t;
      [mouseLeft0, mouseTop0] = cursor.move(self, _l, _t);
    } else {
      mouseLeft1 = _l;
      mouseTop1 = _t;
    }
  }
  const _hideProps = {
    width: 0,
    height: 0,
    left: 0,
    top: 0
  };
  function hideSelect() {
    setSelect(_hideProps, false);
  }
  let downSelectLeft;
  let downSelectTop;
  let downSelectWidth;
  let downSelectHeight;
  function mouseDown(e, src, _l, _t, _w, _h, _i) {
    dragging = true;
    dragX = dragY = drag._x = drag._y = false;
    cacheMouse(e, src, _l, _t, _w, _h, _i, true, false);
    if (e != null) {
      onMouse(mouseup, doc, mouseUp, false);
      pubSync(mousedown, self, mouseLeft0, mouseTop0, plotWidCss, plotHgtCss, null);
    }
    let { left, top, width, height } = select;
    downSelectLeft = left;
    downSelectTop = top;
    downSelectWidth = width;
    downSelectHeight = height;
    hideSelect();
  }
  function mouseUp(e, src, _l, _t, _w, _h, _i) {
    dragging = drag._x = drag._y = false;
    cacheMouse(e, src, _l, _t, _w, _h, _i, false, true);
    let { left, top, width, height } = select;
    let hasSelect = width > 0 || height > 0;
    let chgSelect = downSelectLeft != left || downSelectTop != top || downSelectWidth != width || downSelectHeight != height;
    hasSelect && chgSelect && setSelect(select);
    if (drag.setScale && hasSelect && chgSelect) {
      let xOff = left, xDim = width, yOff = top, yDim = height;
      if (scaleX.ori == 1) {
        xOff = top, xDim = height, yOff = left, yDim = width;
      }
      if (dragX) {
        _setScale(
          xScaleKey,
          posToVal(xOff, xScaleKey),
          posToVal(xOff + xDim, xScaleKey)
        );
      }
      if (dragY) {
        for (let k in scales) {
          let sc = scales[k];
          if (k != xScaleKey && sc.from == null && sc.min != inf) {
            _setScale(
              k,
              posToVal(yOff + yDim, k),
              posToVal(yOff, k)
            );
          }
        }
      }
      hideSelect();
    } else if (cursor.lock) {
      cursor._lock = !cursor._lock;
      updateCursor(null, true, false);
    }
    if (e != null) {
      offMouse(mouseup, doc);
      pubSync(mouseup, self, mouseLeft1, mouseTop1, plotWidCss, plotHgtCss, null);
    }
  }
  function mouseLeave(e, src, _l, _t, _w, _h, _i) {
    if (cursor._lock)
      return;
    setCursorEvent(e);
    let _dragging = dragging;
    if (dragging) {
      let snapH = true;
      let snapV = true;
      let snapProx = 10;
      let dragH, dragV;
      if (scaleX.ori == 0) {
        dragH = dragX;
        dragV = dragY;
      } else {
        dragH = dragY;
        dragV = dragX;
      }
      if (dragH && dragV) {
        snapH = mouseLeft1 <= snapProx || mouseLeft1 >= plotWidCss - snapProx;
        snapV = mouseTop1 <= snapProx || mouseTop1 >= plotHgtCss - snapProx;
      }
      if (dragH && snapH)
        mouseLeft1 = mouseLeft1 < mouseLeft0 ? 0 : plotWidCss;
      if (dragV && snapV)
        mouseTop1 = mouseTop1 < mouseTop0 ? 0 : plotHgtCss;
      updateCursor(null, true, true);
      dragging = false;
    }
    mouseLeft1 = -10;
    mouseTop1 = -10;
    updateCursor(null, true, true);
    if (_dragging)
      dragging = _dragging;
  }
  function dblClick(e, src, _l, _t, _w, _h, _i) {
    if (cursor._lock)
      return;
    setCursorEvent(e);
    autoScaleX();
    hideSelect();
    if (e != null)
      pubSync(dblclick, self, mouseLeft1, mouseTop1, plotWidCss, plotHgtCss, null);
  }
  function syncPxRatio() {
    axes.forEach(syncFontSize);
    _setSize(self.width, self.height, true);
  }
  on(dppxchange, win, syncPxRatio);
  const events = {};
  events.mousedown = mouseDown;
  events.mousemove = mouseMove;
  events.mouseup = mouseUp;
  events.dblclick = dblClick;
  events["setSeries"] = (e, src, idx, opts2) => {
    let seriesIdxMatcher2 = syncOpts.match[2];
    idx = seriesIdxMatcher2(self, src, idx);
    idx != -1 && setSeries(idx, opts2, true, false);
  };
  if (cursor.show) {
    onMouse(mousedown, over, mouseDown);
    onMouse(mousemove, over, mouseMove);
    onMouse(mouseenter, over, (e) => {
      setCursorEvent(e);
      syncRect(false);
    });
    onMouse(mouseleave, over, mouseLeave);
    onMouse(dblclick, over, dblClick);
    cursorPlots.add(self);
    self.syncRect = syncRect;
  }
  const hooks = self.hooks = opts.hooks || {};
  function fire(evName, a1, a2) {
    if (deferHooks)
      hooksQueue.push([evName, a1, a2]);
    else {
      if (evName in hooks) {
        hooks[evName].forEach((fn) => {
          fn.call(null, self, a1, a2);
        });
      }
    }
  }
  (opts.plugins || []).forEach((p) => {
    for (let evName in p.hooks)
      hooks[evName] = (hooks[evName] || []).concat(p.hooks[evName]);
  });
  const seriesIdxMatcher = (self2, src, srcSeriesIdx) => srcSeriesIdx;
  const syncOpts = assign({
    key: null,
    setSeries: false,
    filters: {
      pub: retTrue,
      sub: retTrue
    },
    scales: [xScaleKey, series[1] ? series[1].scale : null],
    match: [retEq, retEq, seriesIdxMatcher],
    values: [null, null]
  }, cursor.sync);
  if (syncOpts.match.length == 2)
    syncOpts.match.push(seriesIdxMatcher);
  cursor.sync = syncOpts;
  const syncKey = syncOpts.key;
  const sync = _sync(syncKey);
  function pubSync(type, src, x, y, w, h, i) {
    if (syncOpts.filters.pub(type, src, x, y, w, h, i))
      sync.pub(type, src, x, y, w, h, i);
  }
  sync.sub(self);
  function pub(type, src, x, y, w, h, i) {
    if (syncOpts.filters.sub(type, src, x, y, w, h, i))
      events[type](null, src, x, y, w, h, i);
  }
  self.pub = pub;
  function destroy() {
    sync.unsub(self);
    cursorPlots.delete(self);
    mouseListeners.clear();
    off(dppxchange, win, syncPxRatio);
    root.remove();
    legendTable == null ? void 0 : legendTable.remove();
    fire("destroy");
  }
  self.destroy = destroy;
  function _init() {
    fire("init", opts, data);
    setData(data || opts.data, false);
    if (pendScales[xScaleKey])
      setScale(xScaleKey, pendScales[xScaleKey]);
    else
      autoScaleX();
    shouldSetSelect = select.show && (select.width > 0 || select.height > 0);
    shouldSetCursor = shouldSetLegend = true;
    _setSize(opts.width, opts.height);
  }
  series.forEach(initSeries);
  axes.forEach(initAxis);
  if (then) {
    if (then instanceof HTMLElement) {
      then.appendChild(root);
      _init();
    } else
      then(self, _init);
  } else
    _init();
  return self;
}
uPlot.assign = assign;
uPlot.fmtNum = fmtNum;
uPlot.rangeNum = rangeNum;
uPlot.rangeLog = rangeLog;
uPlot.rangeAsinh = rangeAsinh;
uPlot.orient = orient;
uPlot.pxRatio = pxRatio;
{
  uPlot.join = join;
}
{
  uPlot.fmtDate = fmtDate;
  uPlot.tzDate = tzDate;
}
uPlot.sync = _sync;
{
  uPlot.addGap = addGap;
  uPlot.clipGaps = clipGaps;
  let paths = uPlot.paths = {
    points
  };
  paths.linear = linear;
  paths.stepped = stepped;
  paths.bars = bars;
  paths.spline = monotoneCubic;
}
const isNum$3 = (v) => typeof v === "number" && Number.isFinite(v);
function fmtPct(v) {
  if (!isNum$3(v)) return "-";
  return v < 10 ? `${v.toFixed(1)}%` : `${Math.round(v)}%`;
}
const UNITS = ["B", "KB", "MB", "GB", "TB"];
function fmtBytes(b) {
  if (!isNum$3(b)) return "-";
  let value = b;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  if (unit === 0) return `${Math.round(value)} B`;
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${UNITS[unit]}`;
}
function slotsText(verdict) {
  const slots = verdict == null ? void 0 : verdict.slots;
  if (!isNum$3(slots)) return "-";
  return slots > 0 ? `room for ${slots} more` : "no room";
}
function fmtDuration(seconds) {
  if (!isNum$3(seconds)) return "-";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) {
    const m = Math.floor(s % 3600 / 60);
    return `${Math.floor(s / 3600)}h${m ? ` ${m}m` : ""}`;
  }
  const h = Math.floor(s % 86400 / 3600);
  return `${Math.floor(s / 86400)}d${h ? ` ${h}h` : ""}`;
}
function fmtTime(ts, seconds = false) {
  if (!isNum$3(ts)) return "-";
  const d = new Date(ts * 1e3);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}${seconds ? `:${p(d.getSeconds())}` : ""}`;
}
const KIND_LABELS = {
  core_saturated: "Core saturated",
  steal_high: "Steal high",
  mem_low: "Memory low",
  disk_low: "Disk low",
  frames_late: "Late frames",
  oom_kill: "OOM kill",
  instance_new: "Instance appeared",
  instance_gone: "Instance gone"
};
function kindLabel(kind) {
  return KIND_LABELS[kind] || String(kind);
}
const text = (v) => typeof v === "string" && v.trim() ? v.trim().replace(/\s+/g, " ") : null;
function cpuCount(hw) {
  if (!isNum$3(hw.vcpus)) return null;
  return hw.hypervisor === false ? `${hw.vcpus} CPU threads` : `${hw.vcpus} vCPU`;
}
function diskText(hw) {
  if (!isNum$3(hw.disk_total)) return null;
  let kind = "disk";
  if (hw.disk_rotational === true) kind = "HDD";
  else if (hw.disk_rotational === false) kind = "SSD";
  return `${fmtBytes(hw.disk_total)} ${kind}`;
}
function productOf(hw) {
  const product = text(hw.product_name);
  if (!product || product === text(hw.provider) || product === text(hw.sys_vendor)) return null;
  return product;
}
function hardwareLine(hw) {
  if (!hw || typeof hw !== "object") return null;
  const provider = text(hw.provider);
  const product = productOf(hw);
  const parts = [
    text(hw.cpu_model),
    cpuCount(hw),
    isNum$3(hw.mem_total) ? `${fmtBytes(hw.mem_total)} RAM` : null,
    diskText(hw),
    provider ? `${provider}${product ? ` (${product})` : ""}` : null
  ].filter(Boolean);
  return parts.length ? parts.join(", ") : null;
}
function hardwareDetails(hw) {
  if (!hw || typeof hw !== "object") return [];
  const out = [];
  const add = (label, value) => {
    if (value) out.push([label, value]);
  };
  add("CPU", text(hw.cpu_model));
  let cores = cpuCount(hw);
  if (cores) {
    const topo = [];
    if (isNum$3(hw.threads_per_core)) topo.push(`${hw.threads_per_core} ${hw.threads_per_core === 1 ? "thread" : "threads"} per core`);
    if (isNum$3(hw.sockets)) topo.push(`${hw.sockets} ${hw.sockets === 1 ? "socket" : "sockets"}`);
    if (topo.length) cores += ` (${topo.join(", ")})`;
  }
  const clock = [cores, isNum$3(hw.mhz) ? `${Math.round(hw.mhz)} MHz` : null, text(hw.cache) ? `cache ${text(hw.cache)}` : null].filter(Boolean);
  add("Cores", clock.length ? clock.join(", ") : null);
  const mem = [];
  if (isNum$3(hw.mem_total)) mem.push(`${fmtBytes(hw.mem_total)} RAM`);
  if (isNum$3(hw.swap_total)) mem.push(hw.swap_total > 0 ? `${fmtBytes(hw.swap_total)} swap` : "no swap");
  add("Memory", mem.length ? mem.join(", ") : null);
  add("Disk", diskText(hw));
  let virt = null;
  if (hw.hypervisor === true) virt = "virtual machine";
  else if (hw.hypervisor === false) virt = "no hypervisor detected";
  const provider = text(hw.provider);
  const extras = [productOf(hw), virt].filter(Boolean);
  if (provider) add("Provider", `${provider}${extras.length ? ` (${extras.join(", ")})` : ""}`);
  else if (virt) add("Provider", virt.charAt(0).toUpperCase() + virt.slice(1));
  const sys = [text(hw.os), text(hw.kernel) ? `kernel ${text(hw.kernel)}` : null].filter(Boolean);
  add("System", sys.length ? sys.join(", ") : null);
  add("Booted", isNum$3(hw.boot_time) ? fmtTime(hw.boot_time) : null);
  return out;
}
const isNum$2 = (v) => typeof v === "number" && Number.isFinite(v);
function pick(row, ...keys) {
  if (!row) return null;
  for (const key of keys) {
    if (isNum$2(row[key])) return row[key];
  }
  return null;
}
function mergeTimes(...lists) {
  const seen = /* @__PURE__ */ new Set();
  for (const rows of lists) {
    for (const r of rows || []) {
      if (isNum$2(r.ts)) seen.add(r.ts);
    }
  }
  return [...seen].sort((a, b) => a - b);
}
function column(rows, xs, fn) {
  const byTs = /* @__PURE__ */ new Map();
  for (const r of rows || []) byTs.set(r.ts, r);
  return xs.map((t) => {
    const r = byTs.get(t);
    return r ? fn(r) : null;
  });
}
function sortedPorts(insts) {
  return Object.keys(insts || {}).map((k) => Number(k)).filter((n) => Number.isInteger(n)).sort((a, b) => a - b);
}
function coreRows(cores, core) {
  return (cores || []).filter((r) => r.core === core);
}
function coreIds(cores) {
  return [...new Set((cores || []).map((r) => r.core).filter(Number.isInteger))].sort((a, b) => a - b);
}
function stackColumns(columns) {
  const n = columns.length ? columns[0].length : 0;
  const out = columns.map(() => new Array(n).fill(null));
  for (let i = 0; i < n; i += 1) {
    let total = 0;
    let any = false;
    columns.forEach((col, k) => {
      if (isNum$2(col[i])) {
        total += col[i];
        any = true;
      }
      out[k][i] = any ? total : null;
    });
  }
  return out;
}
function lastValue(col) {
  for (let i = (col || []).length - 1; i >= 0; i -= 1) {
    if (isNum$2(col[i])) return col[i];
  }
  return null;
}
function eventsTotal(snapshot) {
  const map = (snapshot == null ? void 0 : snapshot.events_24h) || {};
  return Object.values(map).reduce((a, v) => a + (isNum$2(v) ? v : 0), 0);
}
function playersNow(snapshot) {
  const rows = (snapshot == null ? void 0 : snapshot.insts_last) || [];
  const vals = rows.map((r) => r.players).filter(isNum$2);
  return vals.length ? vals.reduce((a, v) => a + v, 0) : null;
}
function diskUsedPct(host) {
  if (!host || !isNum$2(host.disk_used) || !isNum$2(host.disk_total) || host.disk_total <= 0) return null;
  return host.disk_used / host.disk_total * 100;
}
function corePeaks(snapshot) {
  const map = snapshot == null ? void 0 : snapshot.core_p95_24h;
  if (!map || typeof map !== "object") return null;
  const cores = Object.keys(map).map((k) => ({ core: Number(k), p95: map[k] })).filter((c) => Number.isInteger(c.core) && c.core >= 0 && isNum$2(c.p95)).sort((a, b) => a.core - b.core);
  if (!cores.length) return null;
  return { peak: Math.max(...cores.map((c) => c.p95)), cores };
}
function lateFrames24h(snapshot) {
  const insts = snapshot == null ? void 0 : snapshot.insts;
  if (!Array.isArray(insts)) return null;
  let late = 0;
  let frames = 0;
  for (const i of insts) {
    if (isNum$2(i.late_24h)) late += i.late_24h;
    if (isNum$2(i.frames_24h)) frames += i.frames_24h;
  }
  if (frames <= 0) return null;
  return { late, frames, pct: late / frames * 100 };
}
function refNote(verdict) {
  return (verdict == null ? void 0 : verdict.ref_source) === "fleet" ? "fleet reference" : null;
}
const QUIET_KINDS = /* @__PURE__ */ new Set(["instance_new", "instance_gone"]);
const KIND_AREA = {
  core_saturated: "cpu",
  steal_high: "steal",
  mem_low: "memory",
  oom_kill: "memory",
  disk_low: "disk",
  frames_late: "frames"
};
const HEALTH_LABEL = { problem: "Problem", watch: "Watch", nodata: "No data", ok: "OK" };
const HEALTH_RANK = { problem: 0, watch: 1, nodata: 2, ok: 3 };
const STALE_PROBLEM_S = 300;
function openEvents(snapshot) {
  const list = snapshot == null ? void 0 : snapshot.events_open;
  if (!Array.isArray(list)) return null;
  return list.filter((e) => e && e.state === "open" && isNum$2(e.ts)).sort((a, b) => a.ts - b.ts || (a.id || 0) - (b.id || 0));
}
const plural$1 = (n, one, many) => `${n} ${n === 1 ? one : many}`;
function overloadText(verdict) {
  const reason = String((verdict == null ? void 0 : verdict.reason) || "");
  let m = /^frames_late (\d+) with players/.exec(reason);
  if (m) return `${plural$1(Number(m[1]), "late-frame event", "late-frame events")} with players in the last 24 hours.`;
  m = /^core_saturated (\d+) with players/.exec(reason);
  if (m) return `${plural$1(Number(m[1]), "core saturation event", "core saturation events")} with players in the last 24 hours.`;
  return null;
}
function recentEventsText(snapshot) {
  const map = (snapshot == null ? void 0 : snapshot.events_24h) || {};
  const kinds = Object.keys(map).filter((k) => !QUIET_KINDS.has(k) && isNum$2(map[k]) && map[k] > 0).sort();
  if (!kinds.length) return null;
  const n = kinds.reduce((a, k) => a + map[k], 0);
  return `${plural$1(n, "event", "events")} in the last 24 hours (${kinds.map((k) => `${kindLabel(k)} ${map[k]}`).join(", ")}).`;
}
function health(status, reason, items) {
  return { status, label: HEALTH_LABEL[status], reason, items };
}
function hostHealth(row, list) {
  var _a;
  const found = Array.isArray(list) ? list : [];
  const state = row == null ? void 0 : row.state;
  const snapshot = row == null ? void 0 : row.snapshot;
  if (state === "unreachable" || state === "no_sudo") {
    const what = (row == null ? void 0 : row.error) || (state === "no_sudo" ? "The SSH user has no passwordless sudo." : "The host did not answer the SSH query.");
    return health("problem", what, [{ level: "problem", what, since: null }]);
  }
  if (state === "not_installed") {
    return health("nodata", "Host metrics are not installed on this host: use Apply to host.", []);
  }
  if (!row || state === "no_data" || !snapshot || typeof snapshot !== "object") {
    return health("nodata", "The collector has not written any data yet.", []);
  }
  if (state === "stale") {
    const age = snapshot.data_age_s;
    const since = isNum$2(snapshot.now) && isNum$2(age) ? snapshot.now - age : null;
    if (isNum$2(age) && age > STALE_PROBLEM_S) {
      const what2 = `Collector data is ${Math.floor(age / 60)} min old - the collector or the host is down.`;
      return health("problem", what2, [{ level: "problem", what: what2, since }]);
    }
    const data = found.find((f) => (f == null ? void 0 : f.area) === "data");
    const what = (data == null ? void 0 : data.text) || "Collector data is old - the collector or the host is down.";
    return health("watch", what, [{ level: "watch", what, since }]);
  }
  const evItems = [];
  for (const e of openEvents(snapshot) || []) {
    if (QUIET_KINDS.has(e.kind)) continue;
    evItems.push({
      area: KIND_AREA[e.kind] || null,
      level: e.severity === "crit" ? "problem" : "watch",
      what: `${kindLabel(e.kind)}${e.message ? `: ${e.message}` : ""}`,
      since: e.ts
    });
  }
  const findingItems = [];
  for (const f of found) {
    if (!f || f.level !== "problem" && f.level !== "warning") continue;
    const level = f.level === "problem" ? "problem" : "watch";
    const same = evItems.filter((i) => i.area && i.area === f.area);
    if (same.length) {
      if (level === "problem") for (const i of same) i.level = "problem";
      continue;
    }
    findingItems.push({ level, what: f.text, since: null });
  }
  const problems = [];
  const watch = [];
  for (const { area, ...item } of evItems) (item.level === "problem" ? problems : watch).push(item);
  const verdict = row.verdict;
  const overload = (verdict == null ? void 0 : verdict.status) === "overloaded" ? overloadText(verdict) : null;
  if (overload) problems.push({ level: "problem", what: overload, since: null });
  for (const item of findingItems) (item.level === "problem" ? problems : watch).push(item);
  if ((verdict == null ? void 0 : verdict.status) === "overloaded" && !problems.length) {
    problems.push({ level: "problem", what: `Overloaded: ${verdict.reason}.`, since: null });
  }
  if ((verdict == null ? void 0 : verdict.status) === "tight" && !problems.length && !watch.length) {
    watch.push({ level: "watch", what: `Capacity is tight: ${verdict.reason}.`, since: null });
  }
  if (state === "outdated") {
    watch.push({ level: "watch", what: `Collector ${row.version || "version unknown"} is outdated: use Apply to host.`, since: null });
  }
  const recent = recentEventsText(snapshot);
  if (recent && !problems.length && !watch.length) watch.push({ level: "watch", what: recent, since: null });
  const items = [...problems, ...watch];
  if (problems.length) return health("problem", problems[0].what, items);
  if (watch.length) return health("watch", watch[0].what, items);
  if (!verdict || verdict.status === "unknown") {
    return health("nodata", "No data yet", []);
  }
  const room = found.find((f) => (f == null ? void 0 : f.area) === "room");
  return health("ok", (room == null ? void 0 : room.text) || ((_a = found[0]) == null ? void 0 : _a.text) || "All checks passed.", []);
}
function sortByHealth(entries) {
  return [...entries || []].sort((a, b) => {
    var _a, _b, _c, _d;
    return (HEALTH_RANK[(_a = a.health) == null ? void 0 : _a.status] ?? 9) - (HEALTH_RANK[(_b = b.health) == null ? void 0 : _b.status] ?? 9) || String(((_c = a.row) == null ? void 0 : _c.name) || "").localeCompare(String(((_d = b.row) == null ? void 0 : _d.name) || ""), void 0, { sensitivity: "base" });
  });
}
function healthCounts(healths) {
  const out = { problem: 0, watch: 0, nodata: 0, ok: 0 };
  for (const h of healths || []) if (h && h.status in out) out[h.status] += 1;
  return out;
}
function hostIdFromSearch(search) {
  if (typeof search !== "string" || !search) return null;
  const raw = new URLSearchParams(search).get("host");
  if (!raw || !/^\d+$/.test(raw)) return null;
  const id = Number(raw);
  return id > 0 ? id : null;
}
const isNum$1 = (v) => typeof v === "number" && Number.isFinite(v);
const DEFAULT_TICK_MS = 25;
const LATE_FACTOR = 1.5;
const DEFAULTS = {
  verdict_target_pct: 70,
  core_saturated_pct: 95,
  steal_tight_pct: 5,
  disk_low_pct: 90,
  mem_reserve_pct: 20
};
function setting$1(settings, key) {
  const raw = settings == null ? void 0 : settings[key];
  if (raw === null || raw === void 0 || typeof raw === "string" && !raw.trim()) return DEFAULTS[key];
  const n = Number(raw);
  return Number.isFinite(n) ? n : DEFAULTS[key];
}
const num = (v) => String(Math.round(v * 10) / 10);
function chartLimits(settings, tickMs) {
  const target = setting$1(settings, "verdict_target_pct");
  const sat = setting$1(settings, "core_saturated_pct");
  const steal = setting$1(settings, "steal_tight_pct");
  const disk = setting$1(settings, "disk_low_pct");
  const reserve = setting$1(settings, "mem_reserve_pct");
  const tickKnown = isNum$1(tickMs) && tickMs > 0;
  const tick = tickKnown ? tickMs : DEFAULT_TICK_MS;
  const late = tick * LATE_FACTOR;
  return {
    cpu: [
      {
        value: target,
        tone: "warning",
        label: `${num(target)} % planning limit`,
        hint: `Capacity planning keeps every core below ${num(target)} %; sustained load above it means no room for another server.`
      },
      {
        value: sat,
        tone: "critical",
        label: `${num(sat)} % saturated`,
        hint: `Above ${num(sat)} % the core is saturated: server frames come late and players see lag.`
      }
    ],
    steal: [{
      value: steal,
      tone: "warning",
      label: `${num(steal)} % noisy neighbour`,
      hint: `Steal above ${num(steal)} % means other customers of the provider take CPU time from this host.`
    }],
    disk: [{
      value: disk,
      tone: "warning",
      label: `${num(disk)} % disk low`,
      hint: `Above ${num(disk)} % used the collector opens a disk low event.`
    }],
    frameGap: [
      {
        value: tick,
        tone: "neutral",
        label: `${num(tick)} ms tick${tickKnown ? "" : " (default)"}`,
        hint: tickKnown ? `The server runs a frame every ${num(tick)} ms; a gap near this line is normal.` : `No tick measured yet: the QLDS default of 40 frames per second (${num(tick)} ms) is shown.`
      },
      {
        value: late,
        tone: "warning",
        label: `${num(late)} ms late`,
        hint: `A gap above ${num(late)} ms (1.5 ticks) is a late frame: players see a hitch.`
      }
    ],
    tickMs: tick,
    tickKnown,
    lateMs: late,
    memReservePct: reserve,
    /** Used-RAM line where the reserve starts, for a host with `total` bytes of RAM. */
    memReserve(total) {
      if (!isNum$1(total) || total <= 0) return [];
      return [{
        value: total * (1 - reserve / 100),
        tone: "warning",
        label: `${num(reserve)} % reserve`,
        hint: `Capacity planning keeps ${num(reserve)} % of RAM free; used memory above this line eats into it.`
      }];
    }
  };
}
function tickMsOf(series, snapshot) {
  let best = null;
  for (const rows of Object.values((series == null ? void 0 : series.insts) || {})) {
    for (const r of Array.isArray(rows) ? rows : []) {
      if (isNum$1(r == null ? void 0 : r.tick_ms) && r.tick_ms > 0 && isNum$1(r.ts) && (!best || r.ts > best.ts)) best = r;
    }
  }
  if (best) return best.tick_ms;
  for (const r of Array.isArray(snapshot == null ? void 0 : snapshot.insts_last) ? snapshot.insts_last : []) {
    if (isNum$1(r == null ? void 0 : r.tick_ms) && r.tick_ms > 0) return r.tick_ms;
  }
  return null;
}
function peakOf(col) {
  let peak = null;
  for (const v of col || []) {
    if (isNum$1(v) && (peak === null || v > peak)) peak = v;
  }
  return peak;
}
const RANK = { problem: 3, warning: 2, info: 1, ok: 0 };
function findingFor(list, area, { core } = {}) {
  let best = null;
  for (const f of Array.isArray(list) ? list : []) {
    if ((f == null ? void 0 : f.area) !== area) continue;
    if (area === "cpu" && core !== void 0 && !String(f.text).startsWith(`Core ${core} `)) continue;
    if (!best || (RANK[f.level] ?? 0) > (RANK[best.level] ?? 0)) best = f;
  }
  return best;
}
const FALLBACK = {
  surface: "transparent",
  line: "rgba(128, 128, 128, 0.35)",
  lineStrong: "rgba(128, 128, 128, 0.6)",
  ink: "rgb(128, 128, 128)"
};
function readToken(style, name, fallback) {
  if (!style || typeof style.getPropertyValue !== "function") return fallback;
  const v = String(style.getPropertyValue(name) || "").trim();
  return v || fallback;
}
function chartColors(style) {
  const t = (name, fallback) => readToken(style, name, fallback);
  const muted = t("--text-muted", FALLBACK.ink);
  const s0 = t("--hm-s0", muted);
  const slots = [s0];
  for (let i = 1; i <= 8; i += 1) slots.push(t(`--hm-s${i}`, s0));
  return {
    surface: t("--surface-raised", FALLBACK.surface),
    grid: t("--surface-border", FALLBACK.line),
    axis: t("--surface-border-strong", FALLBACK.lineStrong),
    ink: t("--text-primary", FALLBACK.ink),
    ink2: t("--text-secondary", FALLBACK.ink),
    muted,
    tone: {
      warning: t("--accent-warning", FALLBACK.lineStrong),
      critical: t("--accent-danger", FALLBACK.lineStrong),
      neutral: muted
    },
    slots
  };
}
function themeKey(doc2 = typeof document !== "undefined" ? document : void 0) {
  var _a, _b;
  return ((_b = (_a = doc2 == null ? void 0 : doc2.documentElement) == null ? void 0 : _a.classList) == null ? void 0 : _b.contains("dark")) ? "dark" : "light";
}
function watchTheme(onChange, doc2 = typeof document !== "undefined" ? document : void 0, Observer = typeof MutationObserver !== "undefined" ? MutationObserver : void 0) {
  if (!(doc2 == null ? void 0 : doc2.documentElement) || !Observer) return () => {
  };
  const observer = new Observer(() => onChange(themeKey(doc2)));
  observer.observe(doc2.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}
const { useEffect: useEffect$1, useRef: useRef$1, useState: useState$1, useMemo: useMemo$1 } = React;
const SYNC_KEY = "hm-time";
const FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';
function useThemeKey() {
  const [key, setKey] = useState$1(() => themeKey());
  useEffect$1(() => watchTheme(setKey), []);
  return key;
}
function slotVar(slot) {
  return slot >= 1 && slot <= 8 ? `var(--hm-s${slot})` : "var(--hm-s0)";
}
const TONE_VAR = {
  warning: "var(--accent-warning)",
  critical: "var(--accent-danger)",
  neutral: "var(--text-muted)"
};
function seriesColor(colors, slot) {
  return colors.slots[slot >= 1 && slot <= 8 ? slot : 0];
}
function drawThresholds(u, lines, colors) {
  if (!lines || !lines.length) return;
  const pr = uPlot.pxRatio || 1;
  const c = u.ctx;
  const { left, top, width, height } = u.bbox;
  c.save();
  c.font = `${Math.round(11 * pr)}px ${FONT}`;
  c.textAlign = "right";
  const placed = [];
  for (const l of lines) {
    const y = Math.round(u.valToPos(l.value, "y", true)) + 0.5;
    if (!Number.isFinite(y) || y < top || y > top + height) continue;
    c.strokeStyle = colors.tone[l.tone] || colors.muted;
    c.lineWidth = 1.5 * pr;
    c.setLineDash([5 * pr, 4 * pr]);
    c.beginPath();
    c.moveTo(left, y);
    c.lineTo(left + width, y);
    c.stroke();
    c.setLineDash([]);
    const above = y - top > 16 * pr;
    c.textBaseline = above ? "bottom" : "top";
    const ty = above ? y - 3 * pr : y + 3 * pr;
    const tw = c.measureText(l.label).width;
    const boxTop = above ? ty - 13 * pr : ty - 1 * pr;
    let right = left + width - 4 * pr;
    for (const p of placed) {
      if (Math.abs(p.top - boxTop) < 14 * pr) right = Math.min(right, p.left - 10 * pr);
    }
    c.fillStyle = colors.surface;
    c.fillRect(right - tw - 4 * pr, boxTop, tw + 6 * pr, 14 * pr);
    c.fillStyle = colors.ink2;
    c.fillText(l.label, right, ty);
    placed.push({ top: boxTop, left: right - tw - 4 * pr });
  }
  c.restore();
}
function DirectionChip({ direction }) {
  if (direction === "lower") {
    return /* @__PURE__ */ React.createElement("span", { className: "hm-chip", title: "Smaller values are better on this chart." }, /* @__PURE__ */ React.createElement("svg", { viewBox: "0 0 12 12", "aria-hidden": "true" }, /* @__PURE__ */ React.createElement("path", { d: "M6 2v8M3 7l3 3 3-3" })), "Lower is better");
  }
  if (direction === "higher") {
    return /* @__PURE__ */ React.createElement("span", { className: "hm-chip", title: "Larger values are better on this chart." }, /* @__PURE__ */ React.createElement("svg", { viewBox: "0 0 12 12", "aria-hidden": "true" }, /* @__PURE__ */ React.createElement("path", { d: "M6 10V2M3 5l3-3 3 3" })), "Higher is better");
  }
  if (direction === "context") {
    return /* @__PURE__ */ React.createElement("span", { className: "hm-chip", title: "No good or bad value: read it next to the other charts." }, "For context");
  }
  return null;
}
const FINDING_TONE = { problem: "critical", warning: "warning", info: "neutral", ok: "good" };
function FindingLine({ finding }) {
  if (!finding) return null;
  const tone = FINDING_TONE[finding.level] || "neutral";
  const props = {
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true
  };
  let icon;
  if (tone === "good") icon = /* @__PURE__ */ React.createElement("svg", { ...props }, /* @__PURE__ */ React.createElement("circle", { cx: "8", cy: "8", r: "6.5" }), /* @__PURE__ */ React.createElement("path", { d: "M5 8.2l2.2 2.2L11 6" }));
  else if (tone === "warning") icon = /* @__PURE__ */ React.createElement("svg", { ...props }, /* @__PURE__ */ React.createElement("path", { d: "M8 2l6.5 11.5h-13z" }), /* @__PURE__ */ React.createElement("path", { d: "M8 6.5v3M8 11.6v.1" }));
  else if (tone === "critical") icon = /* @__PURE__ */ React.createElement("svg", { ...props }, /* @__PURE__ */ React.createElement("circle", { cx: "8", cy: "8", r: "6.5" }), /* @__PURE__ */ React.createElement("path", { d: "M5.5 5.5l5 5M10.5 5.5l-5 5" }));
  else icon = /* @__PURE__ */ React.createElement("svg", { ...props }, /* @__PURE__ */ React.createElement("circle", { cx: "8", cy: "8", r: "6.5" }), /* @__PURE__ */ React.createElement("path", { d: "M8 7.2v4M8 4.9v.1" }));
  const label = { good: "OK", warning: "Warning", critical: "Problem", neutral: "Note" }[tone];
  return /* @__PURE__ */ React.createElement("div", { className: `hm-finding hm-finding-${tone}` }, /* @__PURE__ */ React.createElement("span", { className: "hm-finding-icon", title: label }, icon), /* @__PURE__ */ React.createElement("span", null, finding.text));
}
function ChartCard({
  title,
  subtitle,
  howTo,
  direction,
  finding,
  series,
  thresholds = [],
  xs,
  columns,
  xRange,
  yFmt,
  axisFmt,
  yLabel,
  yRange,
  stacked = false,
  height = 150,
  seconds = false,
  dim = false,
  emptyText = "No data in this range."
}) {
  const theme = useThemeKey();
  const wrapRef = useRef$1(null);
  const plotRef = useRef$1(null);
  const uRef = useRef$1(null);
  const live = useRef$1({});
  const [hover, setHover] = useState$1(null);
  const [width, setWidth] = useState$1(0);
  const hasData2 = xs.length > 0 && columns.some((c) => c.some((v) => v !== null && v !== void 0));
  const lineSig = thresholds.map((t) => `${t.value}:${t.tone}:${t.label}`).join("|");
  const sig = `${series.map((s) => `${s.label}:${s.slot}:${s.step ? 1 : 0}`).join("|")}|${stacked}|${height}|${theme}|${hasData2}|${lineSig}|${yLabel || ""}`;
  const display = useMemo$1(() => {
    if (!stacked) return { cols: columns, order: series.map((_2, i) => i) };
    const cum = stackColumns(columns);
    const order = series.map((_2, i) => series.length - 1 - i);
    return { cols: order.map((i) => cum[i]), order };
  }, [columns, series, stacked]);
  const peaks = useMemo$1(() => columns.map((c) => peakOf(c)), [columns]);
  live.current = {
    xs,
    display,
    xRange,
    yRange,
    thresholds
  };
  useEffect$1(() => {
    const el = wrapRef.current;
    if (!el) return void 0;
    const measure = () => setWidth(Math.floor(el.clientWidth));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  useEffect$1(() => {
    const host = plotRef.current;
    if (!host || !hasData2 || width < 40) return void 0;
    const colors = chartColors(getComputedStyle(host));
    const font2 = `11px ${FONT}`;
    const axisBase = {
      font: font2,
      stroke: colors.muted,
      grid: { stroke: colors.grid, width: 1 },
      ticks: { show: false },
      border: { stroke: colors.axis, width: 1 }
    };
    const uSeries = [{}].concat(display.order.map((origIdx) => {
      const s = series[origIdx];
      const color = seriesColor(colors, s.slot);
      if (stacked) {
        return {
          label: s.label,
          stroke: colors.surface,
          width: 1.5,
          fill: color,
          points: { show: false },
          spanGaps: false
        };
      }
      return {
        label: s.label,
        stroke: color,
        width: 2,
        points: { show: false },
        spanGaps: false,
        ...s.step ? { paths: uPlot.paths.stepped({ align: 1 }) } : {}
      };
    }));
    const dotColors = [null].concat(display.order.map((origIdx) => seriesColor(colors, series[origIdx].slot)));
    const opts = {
      width,
      height,
      legend: { show: false },
      padding: [8, 8, 0, 0],
      cursor: {
        sync: { key: SYNC_KEY, setSeries: false },
        drag: { x: false, y: false, setScale: false },
        points: {
          size: 8,
          width: 2,
          stroke: () => colors.surface,
          fill: (u2, si) => dotColors[si] || colors.muted
        }
      },
      scales: {
        x: { time: true, range: () => live.current.xRange },
        y: {
          range: (u2, min2, max2) => {
            const [lo, hi] = live.current.yRange(max2);
            let top = hi;
            for (const t of live.current.thresholds || []) {
              if (Number.isFinite(t.value) && t.value * 1.05 > top) top = t.value * 1.15;
            }
            return [lo, top];
          }
        }
      },
      axes: [
        { ...axisBase, size: 28 },
        {
          ...axisBase,
          size: 58,
          values: (u2, vals) => vals.map((v) => (axisFmt || yFmt)(v)),
          ...yLabel ? { label: yLabel, labelSize: 16, labelFont: font2 } : {}
        }
      ],
      series: uSeries,
      hooks: {
        draw: [(u2) => drawThresholds(u2, live.current.thresholds, colors)],
        setCursor: [(u2) => {
          const idx = u2.cursor.idx;
          if (idx === null || idx === void 0 || u2.cursor.left < 0) {
            setHover((h) => h === null ? h : null);
            return;
          }
          const left = u2.over.offsetLeft + u2.cursor.left;
          setHover((h) => h && h.idx === idx && h.left === left ? h : { idx, left });
        }]
      }
    };
    const u = new uPlot(opts, [live.current.xs, ...live.current.display.cols], host);
    uRef.current = u;
    return () => {
      u.destroy();
      uRef.current = null;
    };
  }, [sig, width > 40]);
  useEffect$1(() => {
    if (uRef.current) uRef.current.setData([xs, ...display.cols], true);
  }, [xs, display, xRange]);
  useEffect$1(() => {
    if (uRef.current && width > 40) uRef.current.setSize({ width, height });
  }, [width, height]);
  const fmtValue = (v) => v === null || v === void 0 ? "no data" : yFmt(v);
  const latestAt = (col) => fmtValue(lastValue(col));
  const hoveredAt = (col) => fmtValue(hover ? col[hover.idx] : lastValue(col));
  const flipLeft = hover && width && hover.left > width * 0.6;
  return /* @__PURE__ */ React.createElement("div", { className: `hm-card${dim ? " hm-dim" : ""}` }, /* @__PURE__ */ React.createElement("div", { className: "hm-card-head" }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("span", { className: "hm-card-title" }, title), subtitle ? /* @__PURE__ */ React.createElement("span", { className: "hm-card-sub" }, subtitle) : null), /* @__PURE__ */ React.createElement(DirectionChip, { direction })), howTo ? /* @__PURE__ */ React.createElement("div", { className: "hm-howto" }, howTo) : null, /* @__PURE__ */ React.createElement(FindingLine, { finding }), /* @__PURE__ */ React.createElement("div", { className: "hm-legend" }, series.map((s, i) => /* @__PURE__ */ React.createElement("span", { className: "hm-legend-item", key: s.label, title: s.hint || void 0 }, /* @__PURE__ */ React.createElement(
    "span",
    {
      className: stacked ? "hm-swatch-box" : "hm-swatch-line",
      style: { background: slotVar(s.slot) }
    }
  ), /* @__PURE__ */ React.createElement("span", null, s.label), /* @__PURE__ */ React.createElement("span", { className: "hm-legend-value" }, latestAt(columns[i] || [])), peaks[i] !== null ? /* @__PURE__ */ React.createElement("span", { className: "hm-muted" }, "peak ", yFmt(peaks[i])) : null)), thresholds.map((t) => /* @__PURE__ */ React.createElement("span", { className: "hm-legend-item", key: `t-${t.label}`, title: t.hint || void 0 }, /* @__PURE__ */ React.createElement("span", { className: "hm-swatch-dash", style: { borderColor: TONE_VAR[t.tone] || TONE_VAR.neutral } }), /* @__PURE__ */ React.createElement("span", null, t.label))), /* @__PURE__ */ React.createElement("span", { className: "hm-muted" }, "latest values; peak over the range")), /* @__PURE__ */ React.createElement("div", { className: "hm-chart", ref: wrapRef }, hasData2 ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { ref: plotRef }), hover ? /* @__PURE__ */ React.createElement(
    "div",
    {
      className: "hm-tip",
      style: flipLeft ? { left: hover.left - 12, transform: "translateX(-100%)" } : { left: hover.left + 12 }
    },
    /* @__PURE__ */ React.createElement("div", { className: "hm-tip-time" }, fmtTime(xs[hover.idx], seconds)),
    series.map((s, i) => /* @__PURE__ */ React.createElement("div", { className: "hm-tip-row", key: s.label }, /* @__PURE__ */ React.createElement("span", { className: "hm-swatch-line", style: { background: slotVar(s.slot) } }), /* @__PURE__ */ React.createElement("span", { className: "hm-tip-name" }, s.label), /* @__PURE__ */ React.createElement("span", { className: "hm-tip-val" }, hoveredAt(columns[i] || []))))
  ) : null) : /* @__PURE__ */ React.createElement("div", { className: "hm-chart-empty", style: { height } }, emptyText)));
}
const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const STALE_S = 120;
const RANGE_TEXT = {
  "1h": "the last hour",
  "6h": "the last 6 hours",
  "24h": "the last 24 hours",
  "7d": "the last 7 days",
  "30d": "the last 30 days"
};
function setting(settings, key, fallback) {
  const raw = settings == null ? void 0 : settings[key];
  if (raw === null || raw === void 0 || typeof raw === "string" && !raw.trim()) return fallback;
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
}
const pct0$1 = (v) => `${Math.round(v)}`;
const gb1 = (bytes) => (bytes / 1073741824).toFixed(1);
function p95(values) {
  const v = values.filter(isNum).sort((a, b) => a - b);
  if (!v.length) return null;
  return v[Math.max(Math.ceil(0.95 * v.length) - 1, 0)];
}
const hhmm = (ts) => {
  const d = new Date(ts * 1e3);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}`;
};
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const P95_GLOSS = "p95 = the level it stays under 95 % of the time.";
function bigCount(n) {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1).replace(/\.0$/, "")} million`;
  if (n >= 1e4) return `${Math.round(n / 1e3)} thousand`;
  return String(n);
}
function dataFinding(snapshot) {
  const age = snapshot == null ? void 0 : snapshot.data_age_s;
  if (!isNum(age)) {
    return { level: "info", area: "data", text: "No data collected on this host yet." };
  }
  if (age > STALE_S) {
    return {
      level: "problem",
      area: "data",
      text: `Collector data is ${fmtDuration(age)} old - the collector or the host is down.`
    };
  }
  return null;
}
function coresFromSeries(series) {
  const rows = Array.isArray(series == null ? void 0 : series.cores) ? series.cores : null;
  if (!rows) return null;
  const by = /* @__PURE__ */ new Map();
  for (const r of rows) {
    if (!Number.isInteger(r == null ? void 0 : r.core) || r.core < 0) continue;
    if (!by.has(r.core)) by.set(r.core, []);
    by.get(r.core).push(r);
  }
  if (!by.size) return null;
  return [...by.keys()].sort((a, b) => a - b).map((core) => {
    const list = by.get(core);
    const busy = list.map((r) => r.busy);
    const maxes = list.map((r) => isNum(r.busy_max) ? r.busy_max : r.busy).filter(isNum);
    return { core, p95: p95(busy), max: maxes.length ? Math.max(...maxes) : null };
  }).filter((c) => c.p95 !== null);
}
function coresFromSnapshot(snapshot) {
  const map = snapshot == null ? void 0 : snapshot.core_p95_24h;
  if (!map || typeof map !== "object") return null;
  const list = Object.keys(map).map((k) => ({ core: Number(k), p95: map[k], max: null })).filter((c) => Number.isInteger(c.core) && c.core >= 0 && isNum(c.p95)).sort((a, b) => a.core - b.core);
  return list.length ? list : null;
}
function playersAt(series, from, to) {
  for (const rows of Object.values((series == null ? void 0 : series.insts) || {})) {
    for (const r of rows || []) {
      const p = isNum(r.players) ? r.players : r.players_max;
      if (isNum(r.ts) && r.ts >= from && r.ts <= to && isNum(p) && p >= 2) return true;
    }
  }
  return false;
}
function saturation(events, series, now) {
  const out = /* @__PURE__ */ new Map();
  for (const e of Array.isArray(events) ? events : []) {
    if ((e == null ? void 0 : e.kind) !== "core_saturated" || !isNum(e.ts)) continue;
    const m = /^core (\d+)/.exec(e.message || "");
    if (!m) continue;
    const core = Number(m[1]);
    const end = isNum(e.closed_ts) ? e.closed_ts : isNum(now) ? now : null;
    const cur = out.get(core) || { seconds: null, matches: false };
    if (end !== null) {
      cur.seconds = (cur.seconds || 0) + Math.max(end - e.ts, 0);
      if (series && playersAt(series, e.ts, end)) cur.matches = true;
    }
    out.set(core, cur);
  }
  return out;
}
function cpuFindings({ snapshot, series, events, settings, range }) {
  var _a;
  const target = setting(settings, "verdict_target_pct", 70);
  const sat = setting(settings, "core_saturated_pct", 95);
  const fromSeries = coresFromSeries(series);
  const cores = fromSeries || coresFromSnapshot(snapshot);
  const span = fromSeries ? RANGE_TEXT[range] || "the selected range" : "the last 24 hours";
  const note = fromSeries ? "" : " (24 h snapshot)";
  const out = [];
  const satMap = saturation(events, series, (series == null ? void 0 : series.now) ?? (snapshot == null ? void 0 : snapshot.now));
  const byCore = new Map((cores || []).map((c) => [c.core, c]));
  const ids = [.../* @__PURE__ */ new Set([...byCore.keys(), ...satMap.keys()])].sort((a, b) => a - b);
  for (const id of ids) {
    const c = byCore.get(id);
    const s = satMap.get(id);
    if (s) {
      let dur = "";
      if (s.seconds !== null) {
        dur = s.seconds < 60 ? " for less than a minute" : ` for ${plural(Math.round(s.seconds / 60), "minute", "minutes")}`;
      }
      out.push({
        level: "problem",
        area: "cpu",
        text: `Core ${id} was above ${pct0$1(sat)} %${dur}${s.matches ? ", during matches" : ""}.`
      });
    } else if (c.p95 > target) {
      out.push({
        level: "warning",
        area: "cpu",
        text: `Core ${c.core} p95 was ${pct0$1(c.p95)} % over ${span}${note}, above the ${pct0$1(target)} % planning limit.`
      });
    } else if (fromSeries && isNum(c.max)) {
      out.push({
        level: "ok",
        area: "cpu",
        text: `Core ${c.core} stayed below ${pct0$1(c.max)} % (p95 ${pct0$1(c.p95)} %) over ${span}; limit for planning is ${pct0$1(target)} %.`
      });
    } else {
      out.push({
        level: "ok",
        area: "cpu",
        text: `Core ${c.core} p95 was ${pct0$1(c.p95)} % over ${span}${note}; limit for planning is ${pct0$1(target)} %.`
      });
    }
  }
  if (!cores) {
    const n = (_a = snapshot == null ? void 0 : snapshot.events_24h) == null ? void 0 : _a.core_saturated;
    if (isNum(n) && n > 0 && !satMap.size) {
      out.push({
        level: "warning",
        area: "cpu",
        text: `${plural(n, "core saturation event", "core saturation events")} in the last 24 hours (24 h snapshot).`
      });
    }
  }
  return out;
}
function roomFindings({ snapshot, verdict }) {
  if (!verdict) return [];
  const slots = verdict.slots;
  const ref = verdict.ref_load;
  if (verdict.ref_source === null || verdict.ref_source === void 0 || !isNum(ref)) {
    const anyBusy = ((snapshot == null ? void 0 : snapshot.insts) || []).some((i) => isNum(i == null ? void 0 : i.busy_p95));
    if (anyBusy) return [];
    return [{
      level: "info",
      area: "room",
      text: "No match played on this host yet and no other host has data, so room cannot be estimated."
    }];
  }
  const refText = `reference: one instance uses ${pct0$1(ref)} % of a core in a match`;
  const prefix = verdict.ref_source === "fleet" ? "No match played on this host yet, so room is estimated from other hosts. " : "";
  if (!isNum(slots)) return [];
  if (slots > 0) {
    return [{
      level: "ok",
      area: "room",
      text: `${prefix}Room for ${slots} more ${slots === 1 ? "instance" : "instances"} (${refText}).`
    }];
  }
  const reason = String(verdict.reason || "");
  let why = "";
  if (/^0 slots, memory:/.test(reason)) why = ": RAM is the limit";
  else if (/^0 slots, core \d+:/.test(reason)) why = ` (CPU is the limit; ${refText})`;
  return [{
    level: verdict.status === "overloaded" ? "problem" : "warning",
    area: "room",
    text: `${prefix}No room for more instances${why}.`
  }];
}
function frameStats(snapshot, series) {
  const rowsByPort = (series == null ? void 0 : series.insts) && typeof series.insts === "object" ? series.insts : null;
  const fromSeries = !!rowsByPort && sortedPorts(rowsByPort).length > 0;
  const out = [];
  if (fromSeries) {
    for (const port of sortedPorts(rowsByPort)) {
      let late = 0;
      let frames = 0;
      let worst = null;
      for (const r of rowsByPort[String(port)] || []) {
        if (isNum(r.late)) late += r.late;
        if (isNum(r.frames)) frames += r.frames;
        if (isNum(r.max_ms) && isNum(r.ts) && (!worst || r.max_ms > worst.ms)) {
          const p = isNum(r.players) ? r.players : r.players_max;
          worst = { ms: r.max_ms, ts: r.ts, players: isNum(p) ? p : null };
        }
      }
      out.push({ port, late, frames, worst });
    }
    return { fromSeries, list: out };
  }
  for (const i of Array.isArray(snapshot == null ? void 0 : snapshot.insts) ? snapshot.insts : []) {
    if (!Number.isInteger(i == null ? void 0 : i.port)) continue;
    out.push({
      port: i.port,
      late: isNum(i.late_24h) ? i.late_24h : 0,
      frames: isNum(i.frames_24h) ? i.frames_24h : 0,
      worst: null
    });
  }
  return { fromSeries, list: out };
}
function frameFindings({ snapshot, series, events, settings, range }) {
  const { fromSeries, list } = frameStats(snapshot, series);
  const withFrames = list.filter((s) => s.frames > 0);
  if (!withFrames.length) {
    return [{ level: "info", area: "frames", text: "No frame statistics yet (no instance is running or reporting)." }];
  }
  const span = fromSeries ? RANGE_TEXT[range] || "the selected range" : "the last 24 hours";
  const note = fromSeries ? "" : " (24 h snapshot)";
  const openLate = new Set(
    (Array.isArray(events) ? events : []).filter((e) => (e == null ? void 0 : e.kind) === "frames_late" && e.state === "open" && Number.isInteger(e.port)).map((e) => e.port)
  );
  const limitPct = setting(settings, "frames_late_pct", 1);
  const gapMs = setting(settings, "frame_gap_ms", 100);
  const out = [];
  for (const s of withFrames) {
    if (s.late <= 0) continue;
    const isOpen = openLate.has(s.port);
    const latePct = s.late / s.frames * 100;
    if (!isOpen && latePct <= limitPct && !(s.worst && s.worst.ms > gapMs)) {
      out.push({
        level: "info",
        area: "frames",
        text: `${plural(s.late, "late frame", "late frames")} out of ${bigCount(s.frames)} on :${s.port} in ${span}${note} - normal.`
      });
      continue;
    }
    let text2 = `${plural(s.late, "late frame", "late frames")} on :${s.port}`;
    if (s.worst) {
      text2 += `, worst gap ${Math.round(s.worst.ms)} ms at ${hhmm(s.worst.ts)}`;
      if (s.worst.players !== null) text2 += ` (players: ${s.worst.players})`;
    } else {
      text2 += ` in ${span}${note}`;
    }
    text2 += ". A late frame means players see a hitch.";
    out.push({ level: isOpen ? "problem" : "warning", area: "frames", text: text2 });
  }
  if (!out.length) {
    out.push({ level: "ok", area: "frames", text: `No late server frames in ${span}${note}.` });
  }
  return out;
}
function stealFindings({ snapshot, series, settings, range }) {
  const tight = setting(settings, "steal_tight_pct", 5);
  const over = setting(settings, "steal_overload_pct", 15);
  let value = null;
  let span;
  const rows = Array.isArray(series == null ? void 0 : series.cores) ? series.cores.filter((r) => (r == null ? void 0 : r.core) === -1) : [];
  if (rows.length) {
    value = p95(rows.map((r) => r.steal));
    span = RANGE_TEXT[range] || "the selected range";
  }
  if (value === null && isNum(snapshot == null ? void 0 : snapshot.steal_p95)) {
    value = snapshot.steal_p95;
    span = "the last 7 days";
  }
  if (value === null) return [];
  const shown = value < 10 ? value.toFixed(1) : pct0$1(value);
  const level = value > over ? "problem" : value > tight ? "warning" : "ok";
  return [{
    level,
    area: "steal",
    text: `The provider took ${shown} % of CPU time (steal), p95 over ${span}; above ${pct0$1(tight)} % means a noisy neighbour.`
  }];
}
function memoryFindings({ snapshot, events, settings }) {
  const total = snapshot == null ? void 0 : snapshot.mem_total;
  const avail = snapshot == null ? void 0 : snapshot.mem_avail_now;
  if (!isNum(total) || !isNum(avail) || total <= 0) return [];
  const reserve = setting(settings, "mem_reserve_pct", 20);
  const rss = ((snapshot == null ? void 0 : snapshot.insts) || []).map((i) => i == null ? void 0 : i.rss_max).filter((v) => isNum(v) && v > 0);
  const lowOpen = (Array.isArray(events) ? events : []).some((e) => (e == null ? void 0 : e.kind) === "mem_low" && e.state === "open");
  let text2 = `RAM: ${gb1(avail)} GB free of ${gb1(total)} GB`;
  let level = "ok";
  const spare = avail - reserve / 100 * total;
  if (spare < 0) {
    level = "warning";
    text2 += `, below the ${pct0$1(reserve)} % reserve.`;
  } else if (rss.length) {
    const n = Math.floor(spare / Math.max(...rss));
    text2 += `, enough for about ${n} more ${n === 1 ? "instance" : "instances"}.`;
  } else {
    text2 += ".";
  }
  if (lowOpen) level = "problem";
  return [{ level, area: "memory", text: text2 }];
}
function diskFindings({ snapshot, events, settings }) {
  const pct = diskUsedPct(snapshot == null ? void 0 : snapshot.host);
  if (pct === null) return [];
  const limit = setting(settings, "disk_low_pct", 90);
  const lowOpen = (Array.isArray(events) ? events : []).some((e) => (e == null ? void 0 : e.kind) === "disk_low" && e.state === "open");
  const over = pct > limit || lowOpen;
  return [{
    level: over ? "problem" : "ok",
    area: "disk",
    text: `Disk / is ${pct0$1(pct)} % full${over ? "" : ` (${gb1(snapshot.host.disk_total - snapshot.host.disk_used)} GB free)`}.`
  }];
}
function findings({ snapshot, series, events, settings, range, verdict } = {}) {
  if (!snapshot || typeof snapshot !== "object") {
    return [{ level: "info", area: "data", text: "No data collected on this host yet." }];
  }
  const data = dataFinding(snapshot);
  if (data) return [data];
  const ctx = { snapshot, series, events, settings, range, verdict };
  return [
    ...cpuFindings(ctx),
    ...roomFindings(ctx),
    ...frameFindings(ctx),
    ...stealFindings(ctx),
    ...memoryFindings(ctx),
    ...diskFindings(ctx)
  ];
}
const FAST_RANGES = ["1h", "6h"];
const FAST_INTERVAL_MS = 1e4;
const SLOW_INTERVAL_MS = 6e4;
const SNAPSHOT_INTERVAL_MS = 6e4;
function refreshIntervalMs(range) {
  return FAST_RANGES.includes(range) ? FAST_INTERVAL_MS : SLOW_INTERVAL_MS;
}
function shouldRefresh({
  enabled,
  isOpen,
  visible,
  inFlight,
  lastAttemptAt,
  now,
  intervalMs
}) {
  if (!enabled || !isOpen || !visible || inFlight) return false;
  if (lastAttemptAt === null || lastAttemptAt === void 0) return false;
  return now - lastAttemptAt >= intervalMs;
}
function ageSeconds(at, now) {
  if (at === null || at === void 0) return null;
  return Math.max(0, Math.floor((now - at) / 1e3));
}
function updatedText(at, now) {
  const s = ageSeconds(at, now);
  if (s === null) return "";
  if (s < 60) return `Updated ${s} s ago`;
  return `Updated ${Math.floor(s / 60)} min ago`;
}
const { Modal } = ui;
const { useCallback, useEffect, useMemo, useRef, useState } = React;
const RANGES = ["1h", "6h", "24h", "7d", "30d"];
const RANGE_SECONDS = { "1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800, "30d": 2592e3 };
const MAX_EVENT_ROWS = 100;
const pct0 = (v) => `${Math.round(v)}%`;
const int = (v) => String(Math.round(v));
const ms = (v) => `${v < 10 ? v.toFixed(1) : Math.round(v)} ms`;
const rate = (v) => `${fmtBytes(v)}/s`;
const EMPTY_NO_DATA = "No samples in this range yet. The collector writes one every 10 s; if this stays empty, check the collector status below.";
const EMPTY_NO_FRAMES = "No frame timing in this range: the servers did not report frame statistics (no instance running, or the server plugin does not publish them).";
const AUTO_KEY = "hm-auto-refresh";
function readAuto() {
  try {
    return window.localStorage.getItem(AUTO_KEY) !== "0";
  } catch (e) {
    return true;
  }
}
const isVisible = () => typeof document === "undefined" || document.visibilityState === "visible";
function errorText(e, fallback) {
  var _a, _b, _c;
  return ((_c = (_b = (_a = e == null ? void 0 : e.response) == null ? void 0 : _a.data) == null ? void 0 : _b.error) == null ? void 0 : _c.message) || (e == null ? void 0 : e.message) || fallback;
}
function slotOf(index) {
  return index < 8 ? index + 1 : 0;
}
function SeverityIcon({ severity }) {
  const props = {
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true
  };
  if (severity === "crit") {
    return /* @__PURE__ */ React.createElement("svg", { ...props }, /* @__PURE__ */ React.createElement("circle", { cx: "8", cy: "8", r: "6.5" }), /* @__PURE__ */ React.createElement("path", { d: "M5.5 5.5l5 5M10.5 5.5l-5 5" }));
  }
  if (severity === "warn") {
    return /* @__PURE__ */ React.createElement("svg", { ...props }, /* @__PURE__ */ React.createElement("path", { d: "M8 2l6.5 11.5h-13z" }), /* @__PURE__ */ React.createElement("path", { d: "M8 6.5v3M8 11.6v.1" }));
  }
  return /* @__PURE__ */ React.createElement("svg", { ...props }, /* @__PURE__ */ React.createElement("circle", { cx: "8", cy: "8", r: "6.5" }), /* @__PURE__ */ React.createElement("path", { d: "M8 7.2v4M8 4.9v.1" }));
}
const SEVERITY_TEXT = { crit: "Critical", warn: "Warning", info: "Info" };
const SEVERITY_TONE = { crit: "hm-tone-critical", warn: "hm-tone-warning", info: "hm-tone-neutral" };
function scopeText(ev) {
  if (ev.scope === "instance") return `Port ${ev.port}`;
  if (ev.scope === "core") return "Core";
  return "Host";
}
function EventsTable({ events, dim }) {
  if (!events.length) return /* @__PURE__ */ React.createElement("div", { className: `hm-muted${dim ? " hm-dim" : ""}` }, "No events in this range.");
  const shown = events.slice(0, MAX_EVENT_ROWS);
  return /* @__PURE__ */ React.createElement("div", { className: dim ? "hm-dim" : void 0 }, /* @__PURE__ */ React.createElement("div", { className: "overflow-x-auto" }, /* @__PURE__ */ React.createElement("table", { className: "hm-events" }, /* @__PURE__ */ React.createElement("thead", null, /* @__PURE__ */ React.createElement("tr", null, /* @__PURE__ */ React.createElement("th", null, "Time"), /* @__PURE__ */ React.createElement("th", null, "Severity"), /* @__PURE__ */ React.createElement("th", null, "Event"), /* @__PURE__ */ React.createElement("th", null, "Scope"), /* @__PURE__ */ React.createElement("th", null, "Duration"), /* @__PURE__ */ React.createElement("th", null, "Detail"))), /* @__PURE__ */ React.createElement("tbody", null, shown.map((ev) => /* @__PURE__ */ React.createElement("tr", { key: ev.id }, /* @__PURE__ */ React.createElement("td", { className: "hm-num", style: { whiteSpace: "nowrap" } }, fmtTime(ev.ts, true)), /* @__PURE__ */ React.createElement("td", null, /* @__PURE__ */ React.createElement("span", { className: `hm-sev ${SEVERITY_TONE[ev.severity] || "hm-tone-neutral"}` }, /* @__PURE__ */ React.createElement(SeverityIcon, { severity: ev.severity }), SEVERITY_TEXT[ev.severity] || ev.severity)), /* @__PURE__ */ React.createElement("td", null, kindLabel(ev.kind)), /* @__PURE__ */ React.createElement("td", null, scopeText(ev)), /* @__PURE__ */ React.createElement("td", { className: "hm-num" }, ev.state === "open" ? "ongoing" : fmtDuration((ev.closed_ts || ev.ts) - ev.ts)), /* @__PURE__ */ React.createElement("td", { className: "hm-ink-2" }, ev.message)))))), events.length > shown.length ? /* @__PURE__ */ React.createElement("div", { className: "hm-muted", style: { marginTop: 4 } }, "Showing the newest ", shown.length, " of ", events.length, ".") : null);
}
function buildCharts(series, res) {
  const raw = res === "raw";
  const hostRows = (series == null ? void 0 : series.host) || [];
  const hostXs = mergeTimes(hostRows);
  const hostCol = (fn) => column(hostRows, hostXs, fn);
  const cores = coreIds(series == null ? void 0 : series.cores).map((core) => {
    const rows = coreRows(series.cores, core);
    const xs = mergeTimes(rows);
    return {
      core,
      xs,
      columns: ["user", "system", "steal"].map((k) => column(rows, xs, (r) => pick(r, k)))
    };
  });
  const insts = (series == null ? void 0 : series.insts) || {};
  const ports = sortedPorts(insts);
  const instXs = mergeTimes(...ports.map((p) => insts[String(p)]));
  const perPort = (...keys) => ports.map((p) => column(insts[String(p)], instXs, (r) => pick(r, ...keys)));
  const portSeries = (step, hint) => ports.map((p, i) => ({
    label: `Port ${p}`,
    slot: slotOf(i),
    step,
    hint: hint ? hint(p) : void 0
  }));
  const memTotal = lastValue(hostCol((r) => pick(r, "mem_total")));
  const all = cores.find((c) => c.core < 0);
  return {
    cores,
    steal: all ? { xs: all.xs, column: all.columns[2] } : null,
    hostXs,
    instXs,
    ports,
    portSeries,
    cpu: perPort("cpu", "cpu_avg"),
    players: perPort("players", "players_max"),
    maxGap: perPort("max_ms"),
    late: perPort("late"),
    instMem: perPort("mem", "mem_max"),
    memTotal,
    memUsed: hostCol((r) => {
      const total = pick(r, "mem_total");
      const avail = pick(r, "mem_avail");
      return total === null || avail === null ? null : Math.max(total - avail, 0);
    }),
    swap: hostCol((r) => pick(r, "swap_used")),
    rx: hostCol((r) => pick(r, "rx_bps")),
    tx: hostCol((r) => pick(r, "tx_bps")),
    disk: hostCol((r) => {
      const used = pick(r, "disk_used");
      const total = pick(r, "disk_total");
      return used === null || !total ? null : used / total * 100;
    }),
    lateUnit: raw ? "per 10 s sample" : "per minute"
  };
}
function Footer({ ctx, host, isOpen }) {
  const ctxRef = useRef(ctx);
  ctxRef.current = ctx;
  const [status, setStatus] = useState(null);
  const [statusBusy, setStatusBusy] = useState(false);
  const [enabled, setEnabled] = useState(null);
  const [note, setNote] = useState(null);
  const [applyBusy, setApplyBusy] = useState(false);
  const token = useRef(0);
  const loadStatus = useCallback(async () => {
    if (!(host == null ? void 0 : host.id)) return;
    const mine = ++token.current;
    setStatusBusy(true);
    try {
      const data = await ctxRef.current.api("GET", `hosts/${host.id}/status`);
      if (token.current === mine) setStatus(data);
    } catch (e) {
      if (token.current === mine) setStatus({ error: errorText(e, "Could not read the status.") });
    } finally {
      if (token.current === mine) setStatusBusy(false);
    }
  }, [host == null ? void 0 : host.id]);
  useEffect(() => {
    if (!isOpen || !(host == null ? void 0 : host.id)) return;
    setStatus(null);
    setNote(null);
    setEnabled(null);
    loadStatus();
    ctxRef.current.api("GET", `hosts/${host.id}`).then((d) => setEnabled(Boolean(d == null ? void 0 : d.enabled))).catch(() => {
    });
  }, [isOpen, host == null ? void 0 : host.id, loadStatus]);
  const toggle = async (value) => {
    setEnabled(value);
    try {
      await ctxRef.current.api("PUT", `hosts/${host.id}`, { data: { enabled: value } });
      setNote(value ? "Collection enabled. Use Apply to host to install or start it." : "Collection disabled. Use Apply to host to stop it on the host.");
    } catch (e) {
      setEnabled(!value);
      setNote(errorText(e, "Could not save the switch."));
    }
  };
  const apply = async () => {
    setApplyBusy(true);
    setNote(null);
    try {
      const data = await ctxRef.current.api("POST", `hosts/${host.id}/apply`);
      setNote((data == null ? void 0 : data.message) || "Apply queued.");
    } catch (e) {
      setNote(errorText(e, "Apply failed."));
    } finally {
      setApplyBusy(false);
    }
  };
  let statusText;
  if (statusBusy && !status) statusText = "Checking the collector...";
  else if (status == null ? void 0 : status.error) statusText = status.error;
  else if (status) {
    const version = status.version || "not installed";
    const outdated = status.version && status.expected_version && status.version !== status.expected_version;
    statusText = `Collector ${version}${outdated ? ` (current ${status.expected_version})` : ""} | service ${status.service || "unknown"}` + (status.db_bytes !== null && status.db_bytes !== void 0 ? ` | database ${fmtBytes(status.db_bytes)}` : "");
  } else statusText = "";
  return /* @__PURE__ */ React.createElement("div", { className: "hm-root hm-footer" }, /* @__PURE__ */ React.createElement("span", null, statusText), /* @__PURE__ */ React.createElement(Button, { onClick: loadStatus, disabled: statusBusy }, "Check"), /* @__PURE__ */ React.createElement("label", null, /* @__PURE__ */ React.createElement(
    "input",
    {
      type: "checkbox",
      checked: Boolean(enabled),
      disabled: enabled === null,
      onChange: (e) => toggle(e.target.checked)
    }
  ), "Collect metrics on this host"), /* @__PURE__ */ React.createElement("span", { className: "hm-footer-spacer" }), note ? /* @__PURE__ */ React.createElement("span", { className: "hm-note" }, note) : null, /* @__PURE__ */ React.createElement(Button, { variant: "primary", onClick: apply, disabled: applyBusy }, "Apply to host"));
}
function HostModal({ ctx, host, isOpen, onClose }) {
  var _a;
  const ctxRef = useRef(ctx);
  ctxRef.current = ctx;
  const [range, setRange] = useState("24h");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [series, setSeries] = useState(null);
  const [events, setEvents] = useState([]);
  const [fetchedAt, setFetchedAt] = useState(null);
  const [settings, setSettings] = useState(null);
  const [hostRow, setHostRow] = useState(null);
  const token = useRef(0);
  const [autoRefresh, setAutoRefresh] = useState(readAuto);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [clock, setClock] = useState(() => Date.now());
  const inFlight = useRef(false);
  const attemptAt = useRef(null);
  const snapshotAt = useRef(null);
  const snapshotInFlight = useRef(false);
  const snapshotToken = useRef(0);
  const hostIdRef = useRef(host == null ? void 0 : host.id);
  hostIdRef.current = host == null ? void 0 : host.id;
  const loadSnapshot = useCallback(async (background = false) => {
    if (!(host == null ? void 0 : host.id) || snapshotInFlight.current) return;
    const mine = ++snapshotToken.current;
    snapshotInFlight.current = true;
    snapshotAt.current = Date.now();
    try {
      const d = await ctxRef.current.api("GET", "hosts");
      if (snapshotToken.current !== mine || hostIdRef.current !== host.id) return;
      const r = ((d == null ? void 0 : d.hosts) || []).find((h) => h.id === host.id);
      if (r) setHostRow({ snapshot: r.snapshot, verdict: r.verdict || null, state: r.state });
      else if (!background) setHostRow(null);
    } catch (e) {
    } finally {
      if (snapshotToken.current === mine) snapshotInFlight.current = false;
    }
  }, [host == null ? void 0 : host.id]);
  useEffect(() => {
    if (!isOpen) return void 0;
    let alive = true;
    ctxRef.current.api("GET", "settings").then((d) => {
      if (alive) setSettings(d || null);
    }).catch(() => {
      if (alive) setSettings(null);
    });
    return () => {
      alive = false;
    };
  }, [isOpen]);
  useEffect(() => {
    snapshotToken.current += 1;
    snapshotInFlight.current = false;
    snapshotAt.current = null;
  }, [host == null ? void 0 : host.id]);
  useEffect(() => {
    if (!isOpen || !(host == null ? void 0 : host.id)) return void 0;
    if (host.snapshot !== void 0) {
      setHostRow({ snapshot: host.snapshot, verdict: host.verdict || null, state: host.state });
      if (snapshotAt.current === null) snapshotAt.current = Date.now();
      return void 0;
    }
    setHostRow(null);
    loadSnapshot();
    return void 0;
  }, [isOpen, host == null ? void 0 : host.id, host == null ? void 0 : host.snapshot, host == null ? void 0 : host.verdict, host == null ? void 0 : host.state, loadSnapshot]);
  const load = useCallback(async (background = false) => {
    if (!(host == null ? void 0 : host.id)) return;
    if (background && inFlight.current) return;
    const mine = ++token.current;
    inFlight.current = true;
    attemptAt.current = Date.now();
    if (!background) {
      setLoading(true);
      setError(null);
      setRefreshFailed(false);
    }
    try {
      const params = { range };
      const [s, e] = await Promise.all([
        ctxRef.current.api("GET", `hosts/${host.id}/series`, { params }),
        ctxRef.current.api("GET", `hosts/${host.id}/events`, { params })
      ]);
      if (token.current !== mine) return;
      setSeries(s);
      setEvents((e == null ? void 0 : e.events) || []);
      setFetchedAt(Date.now());
      setRefreshFailed(false);
    } catch (err) {
      if (token.current === mine) {
        if (background) setRefreshFailed(true);
        else setError(errorText(err, "Could not load the metrics."));
      }
    } finally {
      if (token.current === mine) {
        inFlight.current = false;
        if (!background) setLoading(false);
      }
    }
  }, [host == null ? void 0 : host.id, range]);
  useEffect(() => {
    if (isOpen) load();
  }, [isOpen, load]);
  const toggleAuto = (value) => {
    setAutoRefresh(value);
    try {
      window.localStorage.setItem(AUTO_KEY, value ? "1" : "0");
    } catch (e) {
    }
  };
  useEffect(() => {
    if (!isOpen) return void 0;
    setClock(Date.now());
    const tick = () => {
      const t = Date.now();
      setClock(t);
      const state = {
        enabled: autoRefresh,
        isOpen,
        visible: isVisible(),
        now: t
      };
      if (shouldRefresh({
        ...state,
        inFlight: inFlight.current,
        lastAttemptAt: attemptAt.current,
        intervalMs: refreshIntervalMs(range)
      })) load(true);
      if (shouldRefresh({
        ...state,
        inFlight: snapshotInFlight.current,
        lastAttemptAt: snapshotAt.current,
        intervalMs: SNAPSHOT_INTERVAL_MS
      })) loadSnapshot(true);
    };
    const timer = setInterval(tick, 1e3);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [isOpen, autoRefresh, range, load, loadSnapshot]);
  useEffect(() => {
    setSeries(null);
    setEvents([]);
    setError(null);
    setRefreshFailed(false);
  }, [host == null ? void 0 : host.id]);
  const charts = useMemo(() => series ? buildCharts(series, series.res) : null, [series]);
  const now = (series == null ? void 0 : series.now) || Math.floor(Date.now() / 1e3);
  const xRange = useMemo(() => [now - RANGE_SECONDS[(series == null ? void 0 : series.range) || range], now], [now, series == null ? void 0 : series.range, range]);
  const seconds = (series == null ? void 0 : series.res) === "raw";
  const dim = loading && Boolean(series);
  const common = { xRange, seconds, dim };
  const noInstances = charts && charts.ports.length === 0;
  const limits = useMemo(
    () => chartLimits(settings, tickMsOf(series, hostRow == null ? void 0 : hostRow.snapshot)),
    [settings, series, hostRow]
  );
  const allEvents = useMemo(() => {
    const seen = new Set(events.map((e) => e.id));
    return [...events, ...(openEvents(hostRow == null ? void 0 : hostRow.snapshot) || []).filter((e) => !seen.has(e.id))];
  }, [events, hostRow]);
  const found = useMemo(() => hostRow ? findings({
    snapshot: hostRow.snapshot,
    series: series || void 0,
    events: allEvents,
    settings,
    range: (series == null ? void 0 : series.range) || range,
    verdict: hostRow.verdict
  }) : [], [hostRow, series, allEvents, settings, range]);
  const hardware = (_a = hostRow == null ? void 0 : hostRow.snapshot) == null ? void 0 : _a.hardware;
  const hwLine = hardwareLine(hardware);
  const hwRows = hardwareDetails(hardware);
  const lateMs = `${Math.round(limits.lateMs * 10) / 10} ms`;
  const tickMs = `${Math.round(limits.tickMs * 10) / 10} ms`;
  const [planPct, satPct] = limits.cpu.map((t) => `${t.value} %`);
  return /* @__PURE__ */ React.createElement(
    Modal,
    {
      isOpen,
      onClose,
      size: "2xl",
      height: "85vh",
      title: /* @__PURE__ */ React.createElement(React.Fragment, null, "Host Metrics", /* @__PURE__ */ React.createElement("span", { className: "mt-0.5 block font-mono text-xs font-normal normal-case tracking-normal text-theme-secondary" }, host == null ? void 0 : host.name, fetchedAt ? ` | loaded ${fmtTime(fetchedAt / 1e3, true)}` : ""), hwLine ? /* @__PURE__ */ React.createElement(
        "span",
        {
          className: "block text-xs font-normal normal-case tracking-normal text-theme-secondary",
          title: hwRows.map(([k, v]) => `${k}: ${v}`).join(" | ")
        },
        hwLine
      ) : null),
      headerActions: /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(Button, { onClick: load, disabled: loading }, loading ? "Loading..." : "Refresh"), /* @__PURE__ */ React.createElement(Button, { onClick: onClose, "aria-label": "Close" }, "Close")),
      footer: /* @__PURE__ */ React.createElement(Footer, { ctx, host, isOpen })
    },
    /* @__PURE__ */ React.createElement("div", { className: "hm-root hm-modal-body" }, /* @__PURE__ */ React.createElement("div", { className: "hm-controls" }, /* @__PURE__ */ React.createElement("div", { className: "hm-range", role: "group", "aria-label": "Time range" }, RANGES.map((r) => /* @__PURE__ */ React.createElement("button", { key: r, type: "button", "aria-pressed": r === range, onClick: () => setRange(r) }, r))), /* @__PURE__ */ React.createElement("label", { className: "hm-auto" }, /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: autoRefresh, onChange: (e) => toggleAuto(e.target.checked) }), "Auto-refresh"), series ? /* @__PURE__ */ React.createElement("span", { className: "hm-muted" }, series.res === "raw" ? "10 s samples" : "1 minute averages") : null, fetchedAt ? /* @__PURE__ */ React.createElement("span", { className: "hm-muted" }, updatedText(fetchedAt, clock)) : null, refreshFailed ? /* @__PURE__ */ React.createElement("span", { className: "hm-muted" }, "refresh failed, retrying") : null), hostRow ? /* @__PURE__ */ React.createElement("div", { className: "hm-overview" }, /* @__PURE__ */ React.createElement("section", null, /* @__PURE__ */ React.createElement("div", { className: "hm-section-title" }, "Summary"), /* @__PURE__ */ React.createElement("ul", { className: "hm-summary" }, hostRow.state === "outdated" ? /* @__PURE__ */ React.createElement("li", null, /* @__PURE__ */ React.createElement(FindingLine, { finding: { level: "warning", area: "data", text: "The collector on this host is outdated: use Apply to host below." } })) : null, found.map((f, i) => /* @__PURE__ */ React.createElement("li", { key: `${f.area}-${i}` }, /* @__PURE__ */ React.createElement(FindingLine, { finding: f })))), found.some((f) => /p95/.test(f.text)) ? /* @__PURE__ */ React.createElement("div", { className: "hm-muted" }, P95_GLOSS) : null), /* @__PURE__ */ React.createElement("section", null, /* @__PURE__ */ React.createElement("div", { className: "hm-section-title" }, "Hardware"), hwRows.length ? /* @__PURE__ */ React.createElement("dl", { className: "hm-hw" }, hwRows.map(([k, v]) => /* @__PURE__ */ React.createElement(React.Fragment, { key: k }, /* @__PURE__ */ React.createElement("dt", null, k), /* @__PURE__ */ React.createElement("dd", null, v)))) : /* @__PURE__ */ React.createElement("div", { className: "hm-muted" }, "Not read yet: the collector reads it at start and every hour (collector 1.1 or later)."))) : null, error ? /* @__PURE__ */ React.createElement("div", { className: "hm-error" }, error) : null, !series && loading ? /* @__PURE__ */ React.createElement("div", { className: "hm-muted" }, "Loading...") : null, charts ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("section", null, /* @__PURE__ */ React.createElement("div", { className: "hm-section-title" }, "CPU per core"), charts.cores.length === 0 ? /* @__PURE__ */ React.createElement("div", { className: "hm-muted" }, EMPTY_NO_DATA) : /* @__PURE__ */ React.createElement("div", { className: "hm-grid-2" }, charts.cores.map((c) => /* @__PURE__ */ React.createElement(
      ChartCard,
      {
        key: c.core,
        title: c.core < 0 ? "All cores" : `Core ${c.core}`,
        subtitle: "% of the core, stacked",
        howTo: `${c.core < 0 ? "Average load of all cores" : "How busy this core is"}, split by who used it; the top of the stack is the total. Sustained above the dashed ${planPct} line means no room for more servers on it; at ${satPct} the core is saturated and players see lag.`,
        direction: "lower",
        finding: c.core < 0 ? null : findingFor(found, "cpu", { core: c.core }),
        series: [
          { label: "User", slot: 1, hint: "Time spent in programs, the game servers included." },
          { label: "System", slot: 2, hint: "Time spent in the kernel (network, disk, scheduling)." },
          { label: "Steal", slot: 3, hint: "Time the provider gave to other virtual machines on the same hardware." }
        ],
        thresholds: limits.cpu,
        xs: c.xs,
        columns: c.columns,
        stacked: true,
        height: 120,
        yFmt: fmtPct,
        axisFmt: pct0,
        yRange: () => [0, 100],
        emptyText: EMPTY_NO_DATA,
        ...common
      }
    )), charts.steal ? /* @__PURE__ */ React.createElement(
      ChartCard,
      {
        title: "Steal",
        subtitle: "% of CPU time, all cores",
        howTo: `CPU time the provider took for other customers on the same hardware. Sustained above the dashed ${limits.steal[0].value} % line means a noisy neighbour: the host is slower than its specification.`,
        direction: "lower",
        finding: findingFor(found, "steal"),
        series: [{ label: "Steal", slot: 3, hint: "Share of CPU time taken by the hypervisor for other virtual machines." }],
        thresholds: limits.steal,
        xs: charts.steal.xs,
        columns: [charts.steal.column],
        height: 120,
        yFmt: fmtPct,
        axisFmt: pct0,
        yRange: (max2) => [0, Math.max(2, max2 * 1.1)],
        emptyText: EMPTY_NO_DATA,
        ...common
      }
    ) : null)), /* @__PURE__ */ React.createElement("section", null, /* @__PURE__ */ React.createElement("div", { className: "hm-section-title" }, "CPU per instance"), noInstances ? /* @__PURE__ */ React.createElement("div", { className: "hm-muted" }, "No game server ran on this host in this range.") : /* @__PURE__ */ React.createElement("div", { className: "flex flex-col gap-3" }, /* @__PURE__ */ React.createElement(
      ChartCard,
      {
        title: "CPU",
        subtitle: "% of one core",
        howTo: `% of one CPU core used by each server. Sustained above the dashed ${planPct} line means no room for more servers; at ${satPct} the server's core is saturated.`,
        direction: "lower",
        finding: findingFor(found, "room"),
        series: charts.portSeries(false, (p) => `CPU of the server on port ${p}, in % of one core.`),
        thresholds: limits.cpu,
        xs: charts.instXs,
        columns: charts.cpu,
        height: 150,
        yFmt: fmtPct,
        axisFmt: pct0,
        yRange: (max2) => [0, Math.max(100, max2 * 1.1)],
        emptyText: EMPTY_NO_DATA,
        ...common
      }
    ), /* @__PURE__ */ React.createElement(
      ChartCard,
      {
        title: "Players",
        subtitle: "same time axis as CPU",
        howTo: "Players connected to each server. Read it with the CPU chart above: CPU and frame peaks during matches matter, peaks on an empty server do not.",
        direction: "context",
        series: charts.portSeries(true, (p) => `Players connected to the server on port ${p}.`),
        xs: charts.instXs,
        columns: charts.players,
        height: 90,
        yFmt: int,
        yLabel: "players",
        yRange: (max2) => [0, Math.max(4, Math.ceil(max2))],
        emptyText: EMPTY_NO_DATA,
        ...common
      }
    ))), /* @__PURE__ */ React.createElement("section", null, /* @__PURE__ */ React.createElement("div", { className: "hm-section-title" }, "Frame timing per instance"), noInstances ? /* @__PURE__ */ React.createElement("div", { className: "hm-muted" }, "No game server ran on this host in this range.") : /* @__PURE__ */ React.createElement("div", { className: "hm-grid-2" }, /* @__PURE__ */ React.createElement(
      ChartCard,
      {
        title: "Max frame gap",
        subtitle: "ms between two server frames",
        howTo: `Longest pause between two server frames. The server should run a frame every ${tickMs} (first dashed line); a gap above ${lateMs} is a late frame and players see a hitch.`,
        direction: "lower",
        finding: findingFor(found, "frames"),
        series: charts.portSeries(false, (p) => `Longest frame gap of the server on port ${p} in each sample.`),
        thresholds: limits.frameGap,
        xs: charts.instXs,
        columns: charts.maxGap,
        height: 130,
        yFmt: ms,
        yRange: (max2) => [0, Math.max(10, max2 * 1.1)],
        emptyText: EMPTY_NO_FRAMES,
        ...common
      }
    ), /* @__PURE__ */ React.createElement(
      ChartCard,
      {
        title: "Late frames",
        subtitle: charts.lateUnit,
        howTo: `Server frames that came more than ${lateMs} after the previous one, ${charts.lateUnit}. The goal is 0; every late frame is a hitch players can feel.`,
        direction: "lower",
        series: charts.portSeries(true, (p) => `Late frames of the server on port ${p}, ${charts.lateUnit}.`),
        xs: charts.instXs,
        columns: charts.late,
        height: 130,
        yFmt: int,
        yLabel: "frames",
        yRange: (max2) => [0, Math.max(4, Math.ceil(max2 * 1.1))],
        emptyText: EMPTY_NO_FRAMES,
        ...common
      }
    ))), /* @__PURE__ */ React.createElement("section", null, /* @__PURE__ */ React.createElement("div", { className: "hm-section-title" }, "Memory"), /* @__PURE__ */ React.createElement("div", { className: "hm-grid-2" }, /* @__PURE__ */ React.createElement(
      ChartCard,
      {
        title: "Host memory",
        subtitle: charts.memTotal ? `of ${fmtBytes(charts.memTotal)}` : void 0,
        howTo: `RAM in use on the host (the top of the scale is all of it) and swap. Above the dashed line the ${limits.memReservePct} % reserve is eaten into: no room for more servers. Swap in use means RAM ran short.`,
        direction: "lower",
        finding: findingFor(found, "memory"),
        series: [
          { label: "Used", slot: 1, hint: "RAM in use: total minus available." },
          { label: "Swap", slot: 2, hint: "Swap in use; above zero means RAM ran short at some point." }
        ],
        thresholds: limits.memReserve(charts.memTotal),
        xs: charts.hostXs,
        columns: [charts.memUsed, charts.swap],
        height: 130,
        yFmt: fmtBytes,
        yRange: (max2) => [0, charts.memTotal || Math.max(1, max2 * 1.1)],
        emptyText: EMPTY_NO_DATA,
        ...common
      }
    ), noInstances ? null : /* @__PURE__ */ React.createElement(
      ChartCard,
      {
        title: "Memory per instance",
        howTo: "RAM used by each server. A flat line is normal; a line that keeps rising over days points to a leak.",
        direction: "lower",
        series: charts.portSeries(false, (p) => `RAM used by the server on port ${p}.`),
        xs: charts.instXs,
        columns: charts.instMem,
        height: 130,
        yFmt: fmtBytes,
        yRange: (max2) => [0, Math.max(1, max2 * 1.1)],
        emptyText: EMPTY_NO_DATA,
        ...common
      }
    ))), /* @__PURE__ */ React.createElement("section", null, /* @__PURE__ */ React.createElement("div", { className: "hm-section-title" }, "Network and disk"), /* @__PURE__ */ React.createElement("div", { className: "hm-grid-2" }, /* @__PURE__ */ React.createElement(
      ChartCard,
      {
        title: "Network",
        subtitle: "bytes per second",
        howTo: "Traffic in and out of the host. No good or bad value: it grows with players; a jump without players is worth a look.",
        direction: "context",
        series: [
          { label: "Received", slot: 1, hint: "Bytes per second coming into the host." },
          { label: "Sent", slot: 2, hint: "Bytes per second going out of the host." }
        ],
        xs: charts.hostXs,
        columns: [charts.rx, charts.tx],
        height: 130,
        yFmt: rate,
        yRange: (max2) => [0, Math.max(1024, max2 * 1.1)],
        emptyText: EMPTY_NO_DATA,
        ...common
      }
    ), /* @__PURE__ */ React.createElement(
      ChartCard,
      {
        title: "Disk",
        subtitle: "root filesystem used",
        howTo: `Share of the root filesystem (/) in use. Above the dashed ${limits.disk[0].value} % line the collector reports disk low; a full disk stops logs and data from being written.`,
        direction: "lower",
        finding: findingFor(found, "disk"),
        series: [{ label: "Used", slot: 1, hint: "Used space of / in % of its size." }],
        thresholds: limits.disk,
        xs: charts.hostXs,
        columns: [charts.disk],
        height: 130,
        yFmt: fmtPct,
        axisFmt: pct0,
        yRange: () => [0, 100],
        emptyText: EMPTY_NO_DATA,
        ...common
      }
    )))) : null, /* @__PURE__ */ React.createElement("section", null, /* @__PURE__ */ React.createElement("div", { className: "hm-section-title" }, "Events"), /* @__PURE__ */ React.createElement(EventsTable, { events, dim })))
  );
}
function HostPanel({ ctx }) {
  const modal = (ctx == null ? void 0 : ctx.modal) || {};
  return /* @__PURE__ */ React.createElement(HostModal, { ctx, host: modal.entity, isOpen: Boolean(modal.isOpen), onClose: modal.onClose });
}
export {
  Button as B,
  HostModal as H,
  P95_GLOSS as P,
  React as R,
  hostHealth as a,
  fmtTime as b,
  healthCounts as c,
  hardwareLine as d,
  eventsTotal as e,
  findings as f,
  slotsText as g,
  hostIdFromSearch as h,
  corePeaks as i,
  fmtPct as j,
  diskUsedPct as k,
  lateFrames24h as l,
  fmtDuration as m,
  fmtBytes as n,
  openEvents as o,
  playersNow as p,
  HostPanel as q,
  refNote as r,
  sortByHealth as s
};
