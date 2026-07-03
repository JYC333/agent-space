export enum Booking {
  STRICT = "STRICT",
  STRICT_WITH_SIZE = "STRICT_WITH_SIZE",
  NONE = "NONE",
  AVERAGE = "AVERAGE",
  FIFO = "FIFO",
  LIFO = "LIFO",
  HIFO = "HIFO",
}

export function parseBooking(value: string | null | undefined): Booking | null {
  if (value == null || value === "") return null;
  if (Object.values(Booking).includes(value as Booking)) return value as Booking;
  throw new Error(`Invalid booking method: ${value}`);
}
