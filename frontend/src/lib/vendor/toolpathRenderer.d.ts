// Types for ./toolpathRenderer.js -- see that file for provenance and licence.
// three-slicer/viewer/toolpath — 커널 레이어 → GPU 인스턴싱 툴패스.
// three 를 import 하지 않는다: makeToolpath 가 THREE 네임스페이스를 인자로 받는다(단일 인스턴스 보장).

/** 8정점 다이아몬드 단면의 24 삼각형 인덱스 (SegmentTemplate.cpp:18 원본) */
export const VERTEX_DATA: number[]

/** 툴패스 타입 → 색. 0=travel, 1=wall … 11=prime */
export const TYPE_COLOR: Record<number, number[]>
export const TYPE_LABEL: Record<number, string>

/** 파랑→빨강 11색 히트맵 (libvgcode ColorRange.hpp:14) */
export const DEFAULT_RANGES_COLORS: number[][]

export interface ViewTypeDef {
  key: 'feature' | 'speed' | 'height' | 'width' | 'fan' | 'temp'
  label: string
  /** 연속값(히트맵)인가. false 면 고정색. */
  cont: boolean
  unit: string
}
export const VIEW_TYPES: ViewTypeDef[]

/** per-vertex 부가 정보 */
export interface SegmentMeta {
  vType: Uint8Array
  vWidth: Float32Array
  vHeight: Float32Array
  vLayer: Int32Array
}

export interface SegmentData {
  position: Float32Array
  hwa: Float32Array
  segIndex: Uint32Array
  nV: number
  nSeg: number
  layerSegPrefix: Uint32Array
  travelPos: Float32Array
  travelPrefix: Uint32Array
  nTrav: number
  layerCount: number
  maxAbs: number
  hasNaN: boolean
  meta: SegmentMeta
  /** 타입별 총 압출 길이 (index = 툴패스 타입, 길이 16) */
  typeLengths: Float64Array
  /** 정점이 하나도 없으면 null */
  bbox: { min: [number, number, number]; max: [number, number, number] } | null
}

/** 커널 layers[{z, paths(stride8), widths[]}] → GPU 스트림. */
export function buildSegmentData(layers: unknown[], defaultLineWidth: number): SegmentData

/** 타입별 길이 비율(%), pct 내림차순. 시간은 커널이 role 별로 노출하지 않아 길이로 근사한다. */
export function roleRatios(typeLengths: Float64Array | number[]): Array<{
  type: number
  label: string
  pct: number
  color: number[]
}>

/**
 * speed/fan/temp 는 커널 툴패스에 없어 설정값에서 유도한다 — 그 유도에 쓰는 값들.
 */
export interface ColorContext {
  speedByType?: Record<number, number>
  firstLayerSpeed?: number
  fanByType?: Record<number, number>
  fanFirstLayers?: number
  tempNormal?: number
  tempFirst?: number
  closeFanLayers?: number
}

export interface ColorResult {
  /** per-vertex RGBA (nV*4). `.r` 에 색이 packed 돼 있다. */
  color: Float32Array
  min: number
  max: number
  viewType: ViewTypeDef['key']
  label: string
  unit: string
  /** false 면 고정색 — min/max 는 0 이고 범례를 그리면 안 된다. */
  cont: boolean
}

export function computeColors(data: SegmentData, viewType: ViewTypeDef['key'], ctx: ColorContext): ColorResult

export interface ToolpathHandle {
  /** THREE.Mesh — 인자로 넘긴 THREE 네임스페이스의 타입 */
  mesh: any
  /** THREE.LineSegments (travel) */
  travLines: any
  setLayerRange(lo: number, hi: number): void
  /** 하위호환 — setLayerRange(0, n-1) 과 같다. */
  setVisibleLayers(n: number): void
  setTravelVisible(visible: boolean): void
  setColors(color: Float32Array): void
  dispose(): void
  nSeg: number
  layerCount: number
}

/** @param THREE - `import * as THREE from 'three'` 네임스페이스. 소비자 인스턴스를 그대로 쓴다. */
export function makeToolpath(THREE: any, data: SegmentData): ToolpathHandle
