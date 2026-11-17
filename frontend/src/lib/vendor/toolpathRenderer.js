/*
 * GPU-instanced volumetric toolpath renderer.
 *
 * Vendored verbatim from `three-slicer@0.1.1` (`three-slicer/viewer/toolpath`,
 * i.e. viewer/dist/toolpath_gpu.js), which is itself a port of OrcaSlicer's
 * `libvgcode` -- the renderer the desktop slicer draws its own G-code preview
 * with. The diamond segment cross-section, the feature palette and the
 * blue-to-red range ramp all come from there, which is why output built on this
 * matches Studio rather than approximating it.
 *
 *   upstream: https://github.com/kimgh06/Web_Three_Slicer
 *   licence:  AGPL-3.0-or-later (same as Printbuddy)
 *
 * Vendored rather than depended upon: the npm package carries an 8 MB WASM
 * slicing kernel and pins `three@^0.160`, neither of which we want. This module
 * imports nothing -- `makeToolpath` takes the THREE namespace as an argument --
 * so it runs against our own three.js version.
 *
 * Do not edit. To update, re-copy from a newer three-slicer release.
 */
const le = [
  0,
  1,
  2,
  0,
  2,
  3,
  // front spike
  0,
  3,
  4,
  0,
  4,
  5,
  // right/bottom body
  0,
  5,
  6,
  0,
  6,
  1,
  // left/top body
  5,
  4,
  7,
  5,
  7,
  6
  // back spike
], U = {
  0: [0.42, 0.45, 0.5],
  1: [0.85, 0.51, 0.17],
  2: [0.21, 0.45, 0.76],
  3: [0.35, 0.75, 0.85],
  4: [0.16, 0.68, 0.4],
  5: [0.66, 0.42, 0.85],
  6: [0.55, 0.45, 0.35],
  7: [0.95, 0.85, 0.25],
  8: [0.9, 0.35, 0.65],
  9: [0.9, 0.25, 0.25],
  10: [0.6, 0.82, 0.55],
  11: [0.3, 0.72, 0.7]
};
function ie(t) {
  const i = Math.round(t[0] * 255), s = Math.round(t[1] * 255), n = Math.round(t[2] * 255);
  return i << 16 | s << 8 | n;
}
function ue(t, i) {
  const s = t.length, n = i > 0 ? i : 0.42, l = new Array(s);
  for (let e = 0; e < s; e++) {
    const o = t[e].z;
    l[e] = Math.max(0.02, e === 0 ? o : o - t[e - 1].z);
  }
  const a = [], h = [], _ = [], y = [], v = [], r = [], x = [], b = [], A = [], M = [], L = new Float64Array(16), P = [], k = [];
  let W = -1, $ = 0, R = 0, H = 0, E = -1, c = 0;
  const d = 1e-4, u = (e, o, g, m, p, w) => (a.push(e), h.push(o), _.push(g), r.push(m), y.push(p), v.push(w), x.push(c), b.push(!1), a.length - 1);
  for (let e = 0; e < s; e++) {
    const o = t[e].paths, g = t[e].widths, m = l[e];
    if (c = e, !!o)
      for (let p = 0; p < o.length; p += 8) {
        const w = o[p + 3], F = o[p], I = o[p + 1], G = o[p + 2], S = o[p + 4], V = o[p + 5], B = o[p + 6];
        if (w === 0) {
          P.push(F, I, G, S, V, B), k.push(e);
          continue;
        }
        const O = g && g[p / 8] > 0 ? g[p / 8] : n;
        w < 16 && (L[w] += Math.hypot(S - F, V - I));
        let D;
        W >= 0 && E === w && Math.abs($ - F) < d && Math.abs(R - I) < d && Math.abs(H - G) < d ? (D = W, u(S, V, B, w, m, O)) : (D = u(F, I, G, w, m, O), u(S, V, B, w, m, O)), b[D] = !0, W = D + 1, $ = S, R = V, H = B, E = w, A.push(D), M.push(e);
      }
  }
  const f = a.length, C = A.length, z = new Float32Array(f * 4), Y = new Float32Array(f * 4);
  let ee = 0, ne = !1, j = 1 / 0, T = 1 / 0, X = 1 / 0, Z = -1 / 0, q = -1 / 0, J = -1 / 0;
  for (let e = 0; e < f; e++) {
    const o = y[e], g = a[e], m = h[e], p = _[e] - 0.5 * o;
    z[e * 4] = g, z[e * 4 + 1] = m, z[e * 4 + 2] = p;
    const w = e > 0 && b[e - 1], F = b[e];
    let I = 0;
    if (w || F) {
      const G = w ? a[e] - a[e - 1] : 0, S = w ? h[e] - h[e - 1] : 0, V = w ? _[e] - _[e - 1] : 0, B = F ? a[e + 1] - a[e] : 0, O = F ? h[e + 1] - h[e] : 0, D = F ? _[e + 1] - _[e] : 0;
      I = Math.atan2(G * O - S * B, G * B + S * O + V * D);
    }
    Y[e * 4] = o, Y[e * 4 + 1] = v[e], Y[e * 4 + 2] = I, Y[e * 4 + 3] = ie(U[r[e]] || U[1]), (!Number.isFinite(g) || !Number.isFinite(m) || !Number.isFinite(p) || !Number.isFinite(I)) && (ne = !0), ee = Math.max(ee, Math.abs(g), Math.abs(m), Math.abs(p)), g < j && (j = g), g > Z && (Z = g), m < T && (T = m), m > q && (q = m), p < X && (X = p), p > J && (J = p);
  }
  const te = new Uint32Array(C * 4);
  for (let e = 0; e < C; e++)
    te[e * 4] = A[e], te[e * 4 + 1] = M[e];
  const K = { vType: new Uint8Array(f), vWidth: new Float32Array(f), vHeight: new Float32Array(f), vLayer: new Int32Array(f) };
  for (let e = 0; e < f; e++)
    K.vType[e] = r[e], K.vWidth[e] = v[e], K.vHeight[e] = y[e], K.vLayer[e] = x[e];
  const oe = new Int32Array(s + 1);
  {
    let e = 0;
    for (let o = 0; o < s; o++) {
      for (; e < C && M[e] === o; ) e++;
      oe[o + 1] = e;
    }
  }
  const Q = k.length, N = new Float32Array(Q * 6);
  for (let e = 0; e < N.length; e++) N[e] = P[e];
  for (let e = 0; e < N.length; e += 3) {
    const o = N[e], g = N[e + 1], m = N[e + 2];
    o < j && (j = o), o > Z && (Z = o), g < T && (T = g), g > q && (q = g), m < X && (X = m), m > J && (J = m);
  }
  const re = new Int32Array(s + 1);
  {
    let e = 0;
    for (let o = 0; o < s; o++) {
      for (; e < Q && k[e] === o; ) e++;
      re[o + 1] = e;
    }
  }
  const se = f + Q > 0 ? { min: [j, T, X], max: [Z, q, J] } : null;
  return { position: z, hwa: Y, segIndex: te, nV: f, nSeg: C, layerSegPrefix: oe, travelPos: N, travelPrefix: re, nTrav: Q, layerCount: s, maxAbs: ee, hasNaN: ne, meta: K, typeLengths: L, bbox: se };
}
const _e = { 1: "벽", 2: "스파스", 3: "솔리드", 4: "스커트", 5: "서포트", 6: "래프트", 7: "갭필", 8: "씬월", 9: "브리지", 10: "아이어닝", 11: "프라임" };
function ve(t) {
  let i = 0;
  for (let n = 1; n < 16; n++) i += t[n] || 0;
  const s = [];
  if (i <= 0) return s;
  for (let n = 1; n < 16; n++) {
    const l = t[n] || 0;
    l > 0 && s.push({ type: n, label: _e[n] || "t" + n, pct: 100 * l / i, color: U[n] || U[1] });
  }
  return s.sort((n, l) => l.pct - n.pct);
}
const ce = [
  [11, 44, 122],
  [19, 89, 133],
  [28, 136, 145],
  [4, 214, 15],
  [170, 242, 0],
  [252, 249, 3],
  [245, 206, 10],
  [227, 136, 32],
  [209, 104, 48],
  [194, 82, 60],
  [148, 38, 22]
].map((t) => [t[0] / 255, t[1] / 255, t[2] / 255]);
function he(t, i, s, n) {
  const l = n.length;
  if (!(s > i)) return n[0];
  const a = (s - i) / (l - 1), h = (t - i) / a, _ = Math.max(0, Math.min(l - 1, Math.floor(h))), y = Math.max(0, Math.min(l - 1, _ + 1)), v = h - _, r = n[_], x = n[y];
  return [r[0] + (x[0] - r[0]) * v, r[1] + (x[1] - r[1]) * v, r[2] + (x[2] - r[2]) * v];
}
const ae = [
  { key: "feature", label: "Feature type", cont: !1, unit: "" },
  { key: "speed", label: "Speed", cont: !0, unit: "mm/s" },
  { key: "height", label: "Layer Height", cont: !0, unit: "mm" },
  { key: "width", label: "Line Width", cont: !0, unit: "mm" },
  { key: "fan", label: "Fan Speed", cont: !0, unit: "%" },
  { key: "temp", label: "Temperature", cont: !0, unit: "°C" }
];
function de(t, i, s, n) {
  const l = i.vType[s], a = i.vLayer[s], h = a === 0;
  switch (t) {
    case "height":
      return i.vHeight[s];
    case "width":
      return i.vWidth[s];
    case "speed":
      return h ? n.firstLayerSpeed : n.speedByType[l] ?? n.speedByType[1];
    case "fan":
      return a < n.closeFanLayers ? 0 : l === 9 ? 100 : n.fanNormal;
    case "temp":
      return h ? n.tempFirst : n.tempNormal;
    default:
      return 0;
  }
}
function ge(t, i, s) {
  const { meta: n, nV: l } = t, a = new Float32Array(l * 4), h = ae.find((r) => r.key === i) || ae[0];
  if (!h.cont) {
    for (let r = 0; r < l; r++) a[r * 4] = ie(U[n.vType[r]] || U[1]);
    return { color: a, min: 0, max: 0, viewType: i, label: h.label, unit: h.unit, cont: !1 };
  }
  let _ = 1 / 0, y = -1 / 0;
  const v = new Float32Array(l);
  for (let r = 0; r < l; r++) {
    const x = de(i, n, r, s);
    v[r] = x, x < _ && (_ = x), x > y && (y = x);
  }
  Number.isFinite(_) || (_ = 0, y = 1);
  for (let r = 0; r < l; r++) {
    const x = he(v[r], _, y, ce);
    a[r * 4] = ie(x);
  }
  return { color: a, min: _, max: y, viewType: i, label: h.label, unit: h.unit, cont: !0 };
}
const fe = `
precision highp float;
precision highp int;
precision highp sampler2D;
precision highp usampler2D;
#define POINTY_CAPS
#define FIX_TWISTING
const vec3  light_top_dir = vec3(-0.4574957, 0.4574957, 0.7624929);
const float light_top_diffuse = 0.6 * 0.8;
const float light_top_specular = 0.6 * 0.125;
const float light_top_shininess = 20.0;
const vec3  light_front_dir = vec3(0.6985074, 0.1397015, 0.6985074);
const float light_front_diffuse = 0.6 * 0.3;
const float ambient = 0.3;
const float emission = 0.15;
const vec3 UP = vec3(0, 0, 1);
uniform mat4 view_matrix;
uniform mat4 projection_matrix;
uniform vec3 camera_position;
uniform sampler2D position_tex;
uniform sampler2D height_width_angle_tex;
uniform int layer_lo;   // 25단계: 이중 슬라이더 하한(레이어). 범위 밖 세그먼트는 셰이더가 O(1) 클립.
uniform int layer_hi;   //          상한은 instanceCount 로 컷(레이어 순 정렬).
in float vertex_id_float;
in uint seg_id_a_u;     // 인스턴스 어트리뷰트(구 segment_index_tex.r) — 어트리뷰트 fetch 가 texelFetch 보다 쌈
in uint seg_layer_u;    // 인스턴스 어트리뷰트(구 segment_index_tex.g)
out vec3 color;
vec3 decode_color(float col) {
  int c = int(round(col));
  int r = (c >> 16) & 0xFF;
  int g = (c >> 8) & 0xFF;
  int b = (c >> 0) & 0xFF;
  float f = 1.0 / 255.0;
  return f * vec3(r, g, b);
}
float lighting(vec3 eye_position, vec3 eye_normal) {
  float top_diffuse = light_top_diffuse * max(dot(eye_normal, light_top_dir), 0.0);
  float front_diffuse = light_front_diffuse * max(dot(eye_normal, light_front_dir), 0.0);
  float top_specular = light_top_specular * pow(max(dot(-normalize(eye_position), reflect(-light_top_dir, eye_normal)), 0.0), light_top_shininess);
  return ambient + top_diffuse + front_diffuse + top_specular + emission;
}
ivec2 tex_coord(sampler2D sampler, int id) {
  ivec2 tex_size = textureSize(sampler, 0);
  return (tex_size.y == 1) ? ivec2(id, 0) : ivec2(id % tex_size.x, id / tex_size.x);
}
void main() {
  int vertex_id = int(vertex_id_float);
  int seg_layer = int(seg_layer_u);
  if (seg_layer < layer_lo || seg_layer > layer_hi) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }   // 범위 밖 → 클립
  int id_a = int(seg_id_a_u);
  int id_b = id_a + 1;
  vec3 pos_a = texelFetch(position_tex, tex_coord(position_tex, id_a), 0).xyz;
  vec3 pos_b = texelFetch(position_tex, tex_coord(position_tex, id_b), 0).xyz;
  vec3 line = pos_b - pos_a;
  float line_len = length(line);
  vec3 line_dir;
  if (line_len < 1e-4)
    line_dir = vec3(1.0, 0.0, 0.0);
  else
    line_dir = line / line_len;
  vec3 line_right_dir;
  if (abs(dot(line_dir, UP)) > 0.9) {
    line_right_dir = normalize(cross(vec3(1, 0, 0), line_dir));
  }
  else
    line_right_dir = normalize(cross(line_dir, UP));
  vec3 line_up_dir = normalize(cross(line_right_dir, line_dir));
  const vec2 horizontal_vertical_view_signs_array[16] = vec2[](
    vec2(1.0, 0.0), vec2(0.0, 1.0), vec2(0.0, 0.0), vec2(0.0, -1.0),
    vec2(0.0, -1.0), vec2(1.0, 0.0), vec2(0.0, 1.0), vec2(0.0, 0.0),
    vec2(0.0, 1.0), vec2(-1.0, 0.0), vec2(0.0, 0.0), vec2(1.0, 0.0),
    vec2(1.0, 0.0), vec2(0.0, 1.0), vec2(-1.0, 0.0), vec2(0.0, 0.0)
    );
  int id = vertex_id < 4 ? id_a : id_b;
  vec3 endpoint_pos = vertex_id < 4 ? pos_a : pos_b;
  vec4 hwa_color = texelFetch(height_width_angle_tex, tex_coord(height_width_angle_tex, id), 0);   // .xyz=h/w/angle, .w=packed color
  vec3 height_width_angle = hwa_color.xyz;
#ifdef FIX_TWISTING
  int closer_id = (dot(camera_position - pos_a, camera_position - pos_a) < dot(camera_position - pos_b, camera_position - pos_b)) ? id_a : id_b;
  vec3 closer_pos = (closer_id == id_a) ? pos_a : pos_b;
  vec3 camera_view_dir = normalize(closer_pos - camera_position);
  vec3 closer_height_width_angle = texelFetch(height_width_angle_tex, tex_coord(height_width_angle_tex, closer_id), 0).xyz;
  vec3 diagonal_dir_border = normalize(closer_height_width_angle.x * line_up_dir + closer_height_width_angle.y * line_right_dir);
#else
  vec3 camera_view_dir = normalize(endpoint_pos - camera_position);
  vec3 diagonal_dir_border = normalize(height_width_angle.x * line_up_dir + height_width_angle.y * line_right_dir);
#endif
  bool is_vertical_view = abs(dot(camera_view_dir, line_up_dir)) / abs(dot(diagonal_dir_border, line_up_dir)) >
    abs(dot(camera_view_dir, line_right_dir)) / abs(dot(diagonal_dir_border, line_right_dir));
  vec2 signs = horizontal_vertical_view_signs_array[vertex_id + 8 * int(is_vertical_view)];
#ifndef POINTY_CAPS
  if (vertex_id == 2 || vertex_id == 7) signs = -horizontal_vertical_view_signs_array[(vertex_id - 2) + 8 * int(is_vertical_view)];
#endif
  float view_right_sign = sign(dot(-camera_view_dir, line_right_dir));
  float view_top_sign = sign(dot(-camera_view_dir, line_up_dir));
  float half_height = 0.5 * height_width_angle.x;
  float half_width = 0.5 * height_width_angle.y;
  vec3 horizontal_dir = half_width * line_right_dir;
  vec3 vertical_dir = half_height * line_up_dir;
  float horizontal_sign = signs.x * view_right_sign;
  float vertical_sign = signs.y * view_top_sign;
  vec3 pos = endpoint_pos + horizontal_sign * horizontal_dir + vertical_sign * vertical_dir;
  if (vertex_id == 2 || vertex_id == 7) {
    float line_dir_sign = (vertex_id == 2) ? -1.0 : 1.0;
    if (height_width_angle.z == 0.0) {
#ifdef POINTY_CAPS
      pos += line_dir_sign * line_dir * half_width;
#endif
    }
    else {
      pos += line_dir_sign * line_dir * half_width * sin(abs(height_width_angle.z) * 0.5);
      pos += sign(height_width_angle.z) * horizontal_dir * cos(abs(height_width_angle.z) * 0.5);
    }
  }
  vec3 eye_position = (view_matrix * vec4(pos, 1.0)).xyz;
  vec3 eye_normal = (view_matrix * vec4(normalize(pos - endpoint_pos), 0.0)).xyz;
  vec3 color_base = decode_color(hwa_color.w);
  color = color_base * lighting(eye_position, eye_normal);
  gl_Position = projection_matrix * vec4(eye_position, 1.0);
}
`, pe = `
precision highp float;
in vec3 color;
out vec4 fragment_color;
void main() {
  fragment_color = vec4(color, 1.0);
}
`;
function me(t, i) {
  const s = (c, d) => {
    const u = Math.min(2048, Math.max(1, d)), f = Math.max(1, Math.ceil(d / u)), C = new Float32Array(u * f * 4);
    C.set(c.subarray(0, Math.min(c.length, u * f * 4)));
    const z = new t.DataTexture(C, u, f, t.RGBAFormat, t.FloatType);
    return z.minFilter = z.magFilter = t.NearestFilter, z.generateMipmaps = !1, z.needsUpdate = !0, z;
  }, n = s(i.position, i.nV), l = s(i.hwa, i.nV), a = new t.InstancedBufferGeometry();
  a.setIndex(le), a.setAttribute("position", new t.BufferAttribute(new Float32Array(8 * 3), 3)), a.setAttribute("vertex_id_float", new t.BufferAttribute(new Float32Array([0, 1, 2, 3, 4, 5, 6, 7]), 1));
  const h = new t.InstancedInterleavedBuffer(i.segIndex, 4);
  a.setAttribute("seg_id_a_u", new t.InterleavedBufferAttribute(h, 1, 0)), a.setAttribute("seg_layer_u", new t.InterleavedBufferAttribute(h, 1, 1)), a.instanceCount = 0;
  const _ = new t.RawShaderMaterial({
    glslVersion: t.GLSL3,
    uniforms: {
      view_matrix: { value: new t.Matrix4() },
      projection_matrix: { value: new t.Matrix4() },
      camera_position: { value: new t.Vector3() },
      position_tex: { value: n },
      height_width_angle_tex: { value: l },
      layer_lo: { value: 0 },
      layer_hi: { value: i.layerCount }
    },
    vertexShader: fe,
    fragmentShader: pe,
    side: t.DoubleSide
  }), y = new t.Mesh(a, _);
  let v = null;
  if (i.bbox) {
    const { min: c, max: d } = i.bbox, u = new t.Vector3((c[0] + d[0]) / 2, (c[1] + d[1]) / 2, (c[2] + d[2]) / 2), f = Math.hypot(d[0] - c[0], d[1] - c[1], d[2] - c[2]) / 2 + 2;
    v = new t.Sphere(u, f);
  }
  y.frustumCulled = !!v, v && (a.boundingSphere = v);
  const r = new t.Matrix4(), x = new t.Vector3();
  y.onBeforeRender = (c, d, u) => {
    _.uniforms.projection_matrix.value.copy(u.projectionMatrix), _.uniforms.view_matrix.value.multiplyMatrices(u.matrixWorldInverse, y.matrixWorld), r.copy(y.matrixWorld).invert(), u.getWorldPosition(x).applyMatrix4(r), _.uniforms.camera_position.value.copy(x);
  };
  const b = new t.BufferGeometry();
  b.setAttribute("position", new t.BufferAttribute(i.travelPos, 3)), b.setDrawRange(0, 0);
  const A = new t.LineSegments(b, new t.LineBasicMaterial({ color: 7041658 }));
  A.frustumCulled = !!v, A.visible = !1, v && (b.boundingSphere = v);
  let M = !1, L = 0, P = i.layerCount - 1;
  const k = () => {
    const c = i.travelPrefix[L], d = i.travelPrefix[P + 1];
    b.setDrawRange(M ? c * 2 : 0, M ? (d - c) * 2 : 0);
  }, W = (c, d) => {
    const u = i.layerCount;
    L = Math.max(0, Math.min(u - 1, c | 0)), P = Math.max(L, Math.min(u - 1, d | 0)), _.uniforms.layer_lo.value = L, _.uniforms.layer_hi.value = P, a.instanceCount = i.layerSegPrefix[P + 1], k();
  };
  return { mesh: y, travLines: A, setVisibleLayers: (c) => W(0, (c | 0) - 1), setLayerRange: W, setTravelVisible: (c) => {
    M = !!c, A.visible = M, k();
  }, setColors: (c) => {
    const d = l.image.data, u = Math.min(c.length, d.length) / 4;
    for (let f = 0; f < u; f++) d[f * 4 + 3] = c[f * 4];
    l.needsUpdate = !0;
  }, dispose: () => {
    a.dispose(), _.dispose(), n.dispose(), l.dispose(), b.dispose(), A.material.dispose();
  }, nSeg: i.nSeg, layerCount: i.layerCount };
}
export {
  ce as DEFAULT_RANGES_COLORS,
  U as TYPE_COLOR,
  _e as TYPE_LABEL,
  le as VERTEX_DATA,
  ae as VIEW_TYPES,
  ue as buildSegmentData,
  ge as computeColors,
  me as makeToolpath,
  ve as roleRatios
};
