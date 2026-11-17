/**
 * Evaluates OrcaSlicer's `toggle_print_fff_options` enable/disable rules so our
 * process-settings panel greys out the same fields the real slicer does.
 *
 * The vendored `process-toggle-rules.json` carries the rules verbatim from the
 * C++ source: each rule is a list of option keys plus an `enable_if` expression
 * written in C++, referencing named locals that are themselves C++ expressions.
 * Rather than hand-translate a subset (which is what upstream's own evaluator
 * does — 11 of 68 locals, the rest silently enabled), this interprets the
 * expressions directly and resolves locals recursively, so a local defined in
 * terms of three other locals costs nothing extra to support.
 *
 * The cardinal rule is **fail open**: anything we cannot decide with certainty
 * leaves the field enabled. A wrongly-greyed control hides a setting the user
 * needs and looks like a bug; a wrongly-enabled one merely lets them set
 * something the slicer will ignore, which is the pre-existing behaviour of every
 * other settings surface in Printbuddy. Every `undefined` return below is that
 * rule being applied, not an oversight.
 *
 * Deliberately not `eval` / `new Function`: the expressions are vendored data
 * rather than user input, but the frontend runs under a CSP without
 * `unsafe-eval` and a 120-line recursive-descent parser is easier to test than
 * a regex pipeline that rewrites C++ into JavaScript.
 */

import type { ProcessSchema, SettingValue } from '../types/slicerSettings';

/**
 * A read of an enum-typed option, carrying the key so a comparison against a
 * C++ enumerator can be checked against that option's declared values.
 */
interface EnumRead {
  enumKey: string;
  value: string | undefined;
}

/** A resolved expression value. `undefined` means "could not determine". */
type Value = boolean | number | string | EnumRead | undefined;

const isEnumRead = (v: Value): v is EnumRead => typeof v === 'object' && v !== null && 'enumKey' in v;

/** A bare C++ enumerator (`ipGyroid`, `IroningType::NoIroning`) seen in an expression. */
const ENUM_SYMBOL = 'enum:';

// --- Config access ---------------------------------------------------------

export interface ConfigReader {
  /** Raw value for a key: the user's override if set, else the schema default. */
  get(key: string): Value;
  has(key: string): boolean;
}

/** Numeric view of a value: "20%" -> 20, [500] -> 500, "0.42" -> 0.42. */
function asNumber(v: Value): number | undefined {
  if (typeof v === 'number') return v;
  if (typeof v === 'boolean') return v ? 1 : 0;
  if (typeof v !== 'string') return undefined;
  const n = Number.parseFloat(v);
  return Number.isFinite(n) ? n : undefined;
}

function asBoolean(v: Value): boolean | undefined {
  if (typeof v === 'boolean') return v;
  if (typeof v === 'number') return v !== 0;
  if (v === '1' || v === 'true') return true;
  if (v === '0' || v === 'false') return false;
  return undefined;
}

/**
 * Reads settings with schema defaults behind them. Vector options (`coFloats`
 * and friends) are per-extruder; every condition in the rule set tests the
 * first entry, which is what `opt_float_nullable(key, variant_index)` reads for
 * the active variant.
 */
export function makeConfigReader(settings: Record<string, SettingValue>, schema: ProcessSchema): ConfigReader {
  const read = (key: string): Value => {
    let v: unknown = settings[key];
    if (v === undefined || v === '') v = schema[key]?.default;
    if (Array.isArray(v)) v = v[0];
    if (typeof v === 'boolean' || typeof v === 'number' || typeof v === 'string') return v;
    return undefined;
  };
  return { get: read, has: (key) => key in schema };
}

// --- Tokenizer -------------------------------------------------------------

type Token = { kind: 'num'; value: number } | { kind: 'str'; value: string } | { kind: 'id'; value: string } | { kind: 'op'; value: string };

// Longest-first: `->` must be tried before `-`, `<=` before `<`.
const OPERATORS = ['->', '||', '&&', '==', '!=', '<=', '>=', '(', ')', ',', '<', '>', '!'];

function tokenize(src: string): Token[] | undefined {
  const tokens: Token[] = [];
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    if (c === ' ' || c === '\t' || c === '\n') {
      i += 1;
      continue;
    }
    if (c === '"') {
      const end = src.indexOf('"', i + 1);
      if (end < 0) return undefined;
      tokens.push({ kind: 'str', value: src.slice(i + 1, end) });
      i = end + 1;
      continue;
    }
    // C++ float literals carry an `f` suffix (`0.3f`) that the extractor left
    // intact in a few min/max bounds and defaults.
    const num = /^\d+(\.\d*)?f?/.exec(src.slice(i));
    if (num && /^[\d]/.test(c)) {
      tokens.push({ kind: 'num', value: Number.parseFloat(num[0]) });
      i += num[0].length;
      continue;
    }
    const op = OPERATORS.find((o) => src.startsWith(o, i));
    if (op) {
      tokens.push({ kind: 'op', value: op });
      i += op.length;
      continue;
    }
    // Identifiers, including the `->`, `::`, `<>` decorations of the C++
    // accessor forms; the parser strips those apart below.
    const id = /^[A-Za-z_][A-Za-z0-9_]*(::[A-Za-z_][A-Za-z0-9_]*)*/.exec(src.slice(i));
    if (id) {
      tokens.push({ kind: 'id', value: id[0] });
      i += id[0].length;
      continue;
    }
    return undefined; // Unknown character — fail open.
  }
  return tokens;
}

// --- Parser / evaluator ----------------------------------------------------

/** Accessor names that read a config key named by their first string argument. */
const ACCESSORS = new Set([
  'opt_bool',
  'opt_int',
  'opt_float',
  'opt_float_nullable',
  'opt_int_nullable',
  'opt_bool_nullable',
  'opt_enum',
  'opt_string',
  'option',
  'has',
]);

class Evaluator {
  private tokens: Token[] = [];
  private pos = 0;

  private readonly cfg: ConfigReader;
  private readonly locals: Record<string, string>;
  private readonly schema: ProcessSchema;
  /** Locals currently being resolved — guards the (unlikely) cyclic definition. */
  private readonly resolving: Set<string>;
  private readonly memo: Map<string, Value>;

  constructor(cfg: ConfigReader, locals: Record<string, string>, schema: ProcessSchema, resolving: Set<string>, memo: Map<string, Value>) {
    this.cfg = cfg;
    this.locals = locals;
    this.schema = schema;
    this.resolving = resolving;
    this.memo = memo;
  }

  evaluate(expr: string): Value {
    const tokens = tokenize(expr);
    if (!tokens || tokens.length === 0) return undefined;
    this.tokens = tokens;
    this.pos = 0;
    const value = this.parseOr();
    // Trailing tokens mean we misread the grammar; don't trust a partial parse.
    if (this.pos !== this.tokens.length) return undefined;
    return value;
  }

  private peek(): Token | undefined {
    return this.tokens[this.pos];
  }

  private eatOp(op: string): boolean {
    const t = this.peek();
    if (t && t.kind === 'op' && t.value === op) {
      this.pos += 1;
      return true;
    }
    return false;
  }

  private parseOr(): Value {
    let left = this.parseAnd();
    while (this.eatOp('||')) {
      const right = this.parseAnd();
      const l = asBoolean(left);
      const r = asBoolean(right);
      // Short-circuit truth survives an unknown operand: `true || ???` is true.
      if (l === true || r === true) left = true;
      else if (l === undefined || r === undefined) left = undefined;
      else left = l || r;
    }
    return left;
  }

  private parseAnd(): Value {
    let left = this.parseComparison();
    while (this.eatOp('&&')) {
      const right = this.parseComparison();
      const l = asBoolean(left);
      const r = asBoolean(right);
      if (l === false || r === false) left = false;
      else if (l === undefined || r === undefined) left = undefined;
      else left = l && r;
    }
    return left;
  }

  private parseComparison(): Value {
    const left = this.parseUnary();
    for (const op of ['==', '!=', '<=', '>=', '<', '>']) {
      if (this.eatOp(op)) {
        const right = this.parseUnary();
        return compare(left, right, op, this.schema);
      }
    }
    return left;
  }

  private parseUnary(): Value {
    if (this.eatOp('!')) {
      const v = asBoolean(this.parseUnary());
      return v === undefined ? undefined : !v;
    }
    return this.parsePrimary();
  }

  private parsePrimary(): Value {
    const t = this.peek();
    if (!t) return undefined;

    if (t.kind === 'num') {
      this.pos += 1;
      return t.value;
    }
    if (t.kind === 'str') {
      this.pos += 1;
      return t.value;
    }
    if (t.kind === 'op' && t.value === '(') {
      this.pos += 1;
      const v = this.parseOr();
      if (!this.eatOp(')')) return undefined;
      return v;
    }
    if (t.kind !== 'id') return undefined;
    this.pos += 1;

    if (t.value === 'true') return true;
    if (t.value === 'false') return false;

    // `config->opt_bool("key")`, `config->option<ConfigOptionFloat>("key")->value`
    if (t.value === 'config') return this.parseConfigAccess();

    // A bare identifier is either a named local or a C++ enum symbol.
    const local = this.locals[t.value];
    if (local !== undefined) return this.resolveLocal(t.value, local);
    // Not a local, so it is a C++ enumerator; `compare` decides whether it can
    // be matched against the other side's declared enum values.
    return `${ENUM_SYMBOL}${t.value}`;
  }

  /** Consumes the `->accessor<T>("key")` tail after a `config` identifier. */
  private parseConfigAccess(): Value {
    if (!this.eatOp('->')) return undefined;
    const name = this.peek();
    if (!name || name.kind !== 'id' || !ACCESSORS.has(name.value)) return undefined;
    this.pos += 1;

    // Optional `<ConfigOptionFloat>` / `<InfillPattern>` template argument.
    if (this.eatOp('<')) {
      let depth = 1;
      while (depth > 0) {
        const tok = this.peek();
        if (!tok) return undefined;
        this.pos += 1;
        if (tok.kind === 'op' && tok.value === '<') depth += 1;
        if (tok.kind === 'op' && tok.value === '>') depth -= 1;
      }
    }

    if (!this.eatOp('(')) return undefined;
    const arg = this.peek();
    if (!arg || arg.kind !== 'str') return undefined;
    this.pos += 1;
    const key = arg.value;
    // Skip any further arguments (`, variant_index`, `, 0`).
    while (this.eatOp(',')) {
      let depth = 0;
      for (;;) {
        const tok = this.peek();
        if (!tok) return undefined;
        if (tok.kind === 'op' && tok.value === '(') depth += 1;
        if (tok.kind === 'op' && tok.value === ')') {
          if (depth === 0) break;
          depth -= 1;
        }
        if (tok.kind === 'op' && tok.value === ',' && depth === 0) break;
        this.pos += 1;
      }
    }
    if (!this.eatOp(')')) return undefined;

    // `config->option<T>("key")->value` — consume the trailing member access.
    if (this.eatOp('->')) {
      const member = this.peek();
      if (!member || member.kind !== 'id') return undefined;
      this.pos += 1;
    }

    if (name.value === 'has') return this.cfg.has(key);

    const raw = this.cfg.get(key);
    // Tag reads of enum options so a comparison against a C++ enumerator can
    // validate its transliteration against this option's declared values.
    if (this.schema[key]?.enum_values) {
      return { enumKey: key, value: typeof raw === 'string' ? raw : undefined };
    }
    return raw;
  }

  private resolveLocal(name: string, source: string): Value {
    const cached = this.memo.get(name);
    if (cached !== undefined || this.memo.has(name)) return cached;
    if (this.resolving.has(name)) return undefined;

    this.resolving.add(name);
    const nested = new Evaluator(this.cfg, this.locals, this.schema, this.resolving, this.memo);
    const value = nested.evaluate(source);
    this.resolving.delete(name);

    this.memo.set(name, value);
    return value;
  }
}

/**
 * Compares two resolved values.
 *
 * The interesting case is an enum option tested against a C++ enumerator —
 * `config->opt_enum<IroningType>("ironing_type") != IroningType::NoIroning`.
 * OrcaSlicer's enumerator spellings and its serialised config values are
 * related but not identical (`btNoBrim` -> `no_brim`, `NoIroning` ->
 * `no ironing`), so we generate the plausible spellings and only trust the
 * result when exactly one of them is a value the option actually declares.
 * A transliteration that matches nothing yields `undefined`, not a confident
 * `false` that would grey out a field for the wrong reason.
 */
function compare(left: Value, right: Value, op: string, schema: ProcessSchema): Value {
  const symbolSide = typeof left === 'string' && left.startsWith(ENUM_SYMBOL) ? left : typeof right === 'string' && right.startsWith(ENUM_SYMBOL) ? right : undefined;

  if (symbolSide !== undefined) {
    if (op !== '==' && op !== '!=') return undefined;
    const other = symbolSide === left ? right : left;
    if (!isEnumRead(other)) return undefined;

    const declared = schema[other.enumKey]?.enum_values;
    if (!declared || other.value === undefined) return undefined;

    const matches = enumCandidates(symbolSide.slice(ENUM_SYMBOL.length)).filter((c) => declared.includes(c));
    if (matches.length !== 1) return undefined;

    const equal = matches[0] === other.value;
    return op === '==' ? equal : !equal;
  }

  // An enum read compared against anything else is only meaningful by value.
  const l0 = isEnumRead(left) ? left.value : left;
  const r0 = isEnumRead(right) ? right.value : right;

  if (op === '==' || op === '!=') {
    if (l0 === undefined || r0 === undefined) return undefined;
    const equal = typeof l0 === 'string' || typeof r0 === 'string' ? String(l0) === String(r0) : asNumber(l0) === asNumber(r0);
    return op === '==' ? equal : !equal;
  }

  const l = asNumber(l0);
  const r = asNumber(r0);
  if (l === undefined || r === undefined) return undefined;
  if (op === '<') return l < r;
  if (op === '<=') return l <= r;
  if (op === '>') return l > r;
  if (op === '>=') return l >= r;
  return undefined;
}

/**
 * Plausible config spellings for a C++ enumerator.
 *
 * `IroningType::NoIroning` -> ["no_ironing", "no ironing", "noironing"]
 * `btNoBrim`               -> ["no_brim", "no brim", "nobrim"]
 */
function enumCandidates(symbol: string): string[] {
  const bare = symbol.includes('::') ? symbol.slice(symbol.lastIndexOf('::') + 2) : symbol;
  // Enumerators are either bare PascalCase or PascalCase behind a lowercase
  // type tag (ip*, bt*, sms*); try both readings.
  const cores = [bare, /^[a-z]+([A-Z].*)$/.exec(bare)?.[1]].filter((c): c is string => Boolean(c));

  const out = new Set<string>();
  for (const core of cores) {
    const snake = core.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase();
    out.add(snake);
    out.add(snake.replace(/_/g, ' '));
    out.add(snake.replace(/_/g, ''));
  }
  return [...out];
}

// --- Public API ------------------------------------------------------------

export interface ToggleRules {
  locals: Record<string, string>;
  rules: Array<{ fields: string[]; enable_if: string }>;
}

/**
 * Returns the set of option keys the current settings disable.
 *
 * Only rules that evaluate to a definite `false` contribute; unknown and true
 * both leave the field enabled.
 */
export function disabledKeys(settings: Record<string, SettingValue>, schema: ProcessSchema, toggles: ToggleRules): Set<string> {
  const cfg = makeConfigReader(settings, schema);
  const memo = new Map<string, Value>();
  const disabled = new Set<string>();

  for (const rule of toggles.rules) {
    // The C++ helper takes `(expr, variant_index)`; only the first part is the
    // condition, the rest selects which extruder variant to read.
    const condition = splitCondition(rule.enable_if);
    if (!condition) continue;
    const evaluator = new Evaluator(cfg, toggles.locals, schema, new Set(), memo);
    if (asBoolean(evaluator.evaluate(condition)) === false) {
      for (const field of rule.fields) disabled.add(field);
    }
  }
  return disabled;
}

/**
 * Takes the condition off an `enable_if` payload, dropping a trailing
 * `variant_index` argument. Only parentheses count towards nesting: every
 * argument-bearing call in the rule set is parenthesised, while `<` and `>`
 * appear far more often as comparisons than as template brackets.
 */
function splitCondition(expr: string): string | undefined {
  let depth = 0;
  for (let i = 0; i < expr.length; i += 1) {
    const c = expr[i];
    if (c === '(') depth += 1;
    else if (c === ')') depth -= 1;
    else if (c === ',' && depth === 0) return expr.slice(0, i).trim() || undefined;
  }
  return expr.trim() || undefined;
}
