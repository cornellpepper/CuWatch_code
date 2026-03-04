#pragma once

#include <stdint.h>
#include <stdbool.h>

/*
 * Fixed-size circular buffer for float values.
 * Direct C translation of src/RingBuffer.py.
 * NOT thread-safe — access from a single core/task only.
 */
typedef struct {
  float *buf;    /* External storage array (caller-allocated) */
  uint32_t size; /* Capacity of buf[] */
  uint32_t head; /* Index of oldest element */
  uint32_t tail; /* Index of next write position */
  bool is_full;  /* true when tail wraps to head */
} ring_buffer_t;

/* Initialize ring buffer with caller-provided storage.
 * storage must point to an array of 'size' floats. */
void rb_init(ring_buffer_t *rb, float *storage, uint32_t size);

/* Append a value, overwriting the oldest if the buffer is full. */
void rb_push(ring_buffer_t *rb, float val);

/* Return the arithmetic mean of all stored values.
 * Returns a tiny non-zero value if the buffer is empty (avoids divide-by-zero
 * in rate = 1000.0 / average_dt). */
float rb_average(const ring_buffer_t *rb);

/* True if no values have been appended since init or clear. */
bool rb_is_empty(const ring_buffer_t *rb);

/* Reset the buffer (zero all elements, reset head/tail). */
void rb_clear(ring_buffer_t *rb);
