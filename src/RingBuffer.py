"""A ring buffer is a fixed-size buffer that overwrites the oldest values when full."""
import array

class RingBuffer:
    def __init__(self, size, typecode='I'):
        """Initialize the ring buffer with a fixed size."""
        self.size = size
        self.buffer = array.array(typecode, [0] * size)  # Unsigned integers array
        self.head = 0  # Points to the oldest element
        self.tail = 0  # Points to the next write position
        self.is_full = False  # Indicates if the buffer is full
        self.current = 0  # Iterator current position

    def append(self, value):
        """Add a new unsigned integer to the buffer."""
        self.buffer[self.tail] = value
        if self.is_full:
            # Move head forward if buffer is full (overwrite oldest value)
            self.head = (self.head + 1) % self.size
        self.tail = (self.tail + 1) % self.size
        self.is_full = self.tail == self.head

    def get(self):
        """Retrieve all items from the buffer in order."""
        if self.is_full:
            # If the buffer is full, return items starting from head
            return [self.buffer[i % self.size] for i in range(self.head, self.head + self.size)]
        else:
            # If the buffer is not full, return items from 0 to tail
            return [self.buffer[i] for i in range(self.tail)]

    def is_empty(self):
        """Check if the buffer is empty."""
        return self.tail == self.head and not self.is_full

    def clear(self):
        """Clear the buffer."""
        self.head = 0
        self.tail = 0
        self.is_full = False
        self.buffer = array.array('I', [0] * self.size)

    def calculate_average(self):
        """Calculate the average of the values in the buffer, returning a float."""
        if self.is_empty():
            return 0.0  # Return 0.0 as a float if the buffer is empty
        items = self.get()
        return float(sum(items)) / len(items)  # Ensure the result is a float

    def __iter__(self):
        """Return the iterator object itself."""
        self.current = self.head if self.is_full else 0
        return self

    def __next__(self):
        """Return the next value from the buffer."""
        if self.is_empty() or (not self.is_full and self.current == self.tail):
            raise StopIteration
        value = self.buffer[self.current]
        self.current = (self.current + 1) % self.size
        if self.current == self.tail and not self.is_full:
            raise StopIteration
        return value
    
    def get_head(self):
        """Return the head value of the buffer."""
        if self.is_empty():
            return None  # Return None if the buffer is empty
        return self.buffer[self.head]
    
    def get_tail(self):
        """Return the tail value of the buffer."""
        if self.is_empty():
            return None
        return self.buffer[self.tail - 1]

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
