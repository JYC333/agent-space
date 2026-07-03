export interface DecimalValue {
  readonly decimal: string;
  readonly scale: number;
  readonly coefficient: bigint;
}

const DECIMAL_RE = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;

export function parseDecimal(input: string | DecimalValue): DecimalValue {
  if (typeof input !== "string") return input;
  const raw = input.trim();
  if (!DECIMAL_RE.test(raw)) {
    throw new Error(`Invalid decimal value: ${input}`);
  }

  const negative = raw.startsWith("-");
  const unsigned = raw.replace(/^[+-]/, "");
  const [wholeRaw = "", fractionalRaw = ""] = unsigned.split(".");
  const scale = fractionalRaw.length;
  const whole = stripLeadingZeros(wholeRaw || "0");
  const digits = `${whole}${fractionalRaw}` || "0";
  const coefficient = BigInt(digits) * (negative ? -1n : 1n);
  const decimal = formatCoefficient(coefficient, scale);
  return Object.freeze({ decimal, scale, coefficient });
}

export function decimalFromCoefficient(coefficient: bigint, scale: number): DecimalValue {
  if (!Number.isInteger(scale) || scale < 0) {
    throw new Error(`Invalid decimal scale: ${scale}`);
  }
  return Object.freeze({
    decimal: formatCoefficient(coefficient, scale),
    scale,
    coefficient,
  });
}

export function addDecimal(left: DecimalValue, right: DecimalValue): DecimalValue {
  const scale = Math.max(left.scale, right.scale);
  const coefficient = scaleCoefficient(left, scale) + scaleCoefficient(right, scale);
  return decimalFromCoefficient(coefficient, scale);
}

export function negateDecimal(value: DecimalValue): DecimalValue {
  return decimalFromCoefficient(-value.coefficient, value.scale);
}

export function multiplyDecimal(left: DecimalValue, right: DecimalValue): DecimalValue {
  return decimalFromCoefficient(
    left.coefficient * right.coefficient,
    left.scale + right.scale,
  );
}

export function compareDecimal(left: DecimalValue, right: DecimalValue): number {
  const scale = Math.max(left.scale, right.scale);
  const leftCoefficient = scaleCoefficient(left, scale);
  const rightCoefficient = scaleCoefficient(right, scale);
  if (leftCoefficient === rightCoefficient) return 0;
  return leftCoefficient < rightCoefficient ? -1 : 1;
}

export function isZeroDecimal(value: DecimalValue): boolean {
  return value.coefficient === 0n;
}

export function decimalEquals(left: DecimalValue, right: DecimalValue): boolean {
  return compareDecimal(left, right) === 0;
}

function scaleCoefficient(value: DecimalValue, scale: number): bigint {
  return value.coefficient * 10n ** BigInt(scale - value.scale);
}

function stripLeadingZeros(input: string): string {
  const stripped = input.replace(/^0+(?=\d)/, "");
  return stripped || "0";
}

function formatCoefficient(coefficient: bigint, scale: number): string {
  const negative = coefficient < 0n;
  const absolute = negative ? -coefficient : coefficient;
  if (scale === 0) return `${negative && absolute !== 0n ? "-" : ""}${absolute.toString()}`;

  const padded = absolute.toString().padStart(scale + 1, "0");
  const whole = stripLeadingZeros(padded.slice(0, -scale));
  const fractional = padded.slice(-scale);
  const sign = negative && absolute !== 0n ? "-" : "";
  return `${sign}${whole}.${fractional}`;
}
