#include "ring_buffer.h"
#include <string.h>

void rb_init(ring_buffer_t *rb, float *storage, uint32_t size)
{
  rb->buf = storage;
  rb->size = size;
  rb->head = 0;
  rb->tail = 0;
  rb->is_full = false;
  memset(storage, 0, size * sizeof(float));
}

void rb_push(ring_buffer_t *rb, float val)
{
  rb->buf[rb->tail] = val;
  if (rb->is_full) {
    /* Overwrite oldest: advance head */
    rb->head = (rb->head + 1) % rb->size;
  }
  rb->tail = (rb->tail + 1) % rb->size;
  rb->is_full = (rb->tail == rb->head);
}

float rb_average(const ring_buffer_t *rb)
{
  if (rb_is_empty(rb)) {
    return 0.00000001f; /* Tiny non-zero to avoid divide-by-zero in rate calc */
  }
  double total = 0.0;
  uint32_t count;
  uint32_t idx;

  if (rb->is_full) {
    count = rb->size;
    idx = rb->head;
  }
  else {
    count = rb->tail; /* tail == number of entries when not full and head == 0 */
    idx = 0;          /* Data is stored from index 0 when not yet wrapped */
  }

  for (uint32_t i = 0; i < count; i++) {
    total += rb->buf[(idx + i) % rb->size];
  }
  return (float)(total / count);
}

bool rb_is_empty(const ring_buffer_t *rb)
{
  return (rb->tail == rb->head) && !rb->is_full;
}

void rb_clear(ring_buffer_t *rb)
{
  rb->head = 0;
  rb->tail = 0;
  rb->is_full = false;
  memset(rb->buf, 0, rb->size * sizeof(float));
}
