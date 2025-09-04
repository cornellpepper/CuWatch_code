"""A ring buffer is a fixed-size buffer that overwrites the oldest values when full."""
import array

class RingBuffer:
    def __init__(self, size, typecode='I'):
        """Initialize the ring buffer with a fixed size."""
        self.size = size
        self.typecode = typecode
        self.buffer = array.array(typecode, [0] * size)
        self.head = 0
        self.tail = 0
        self.is_full = False

    def append(self, value):
        self.buffer[self.tail] = value
        if self.is_full:
            # Move head forward if buffer is full (overwrite oldest value)
            self.head = (self.head + 1) % self.size
        self.tail = (self.tail + 1) % self.size
        self.is_full = self.tail == self.head

    def __iter__(self):
        idx = self.head if self.is_full else 0
        count = self.size if self.is_full else self.tail
        for _ in range(count):
            yield self.buffer[idx]
            idx = (idx + 1) % self.size

    def is_empty(self):
        return self.tail == self.head and not self.is_full

    def clear(self):
        self.head = 0
        self.tail = 0
        self.is_full = False
        for i in range(self.size):
            self.buffer[i] = 0

    def calculate_average(self):
        if self.is_empty():
            return 0.00000001
        total = 0
        count = 0
        for value in self:
            total += value
            count += 1
        return 1.0 * total / count

    def get_head(self):
        if self.is_empty():
            return None
        return self.buffer[self.head]

    def get_tail(self):
        if self.is_empty():
            return None
        return self.buffer[(self.tail - 1) % self.size]

    def get(self):
        """Retrieve all items from the buffer in order."""
        if self.is_empty():
            return []

        if self.is_full:
            # Two-slice wraparound avoids per-element modulo
            if self.head == 0:
                return list(self.buffer)
            return list(self.buffer[self.head:]) + list(self.buffer[:self.head])
        else:
            # Not full => valid data is [0:tail)
            return list(self.buffer[:self.tail])


# Example usage:
# buffer = RingBuffer(5)

# # Adding values to the buffer
# buffer.append(10)
# buffer.append(20)
# buffer.append(30)
# buffer.append(40)
# buffer.append(50)

# # The buffer is full now, so adding more will overwrite the oldest value
# buffer.append(60)  # Overwrites 10

# # Iterate over the buffer
# for value in buffer:
#     print(value)
# buffer.append(10)
# buffer.append(20)
# buffer.append(30)
# buffer.append(40)
# buffer.append(50)

# # The buffer is full now, so adding more will overwrite the oldest value
# buffer.append(60)  # Overwrites 10

# # Iterate over the buffer
# for value in buffer:
#     print(value)
