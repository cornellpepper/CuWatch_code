import array

class RingBuffer:
    def __init__(self, size):
        """Initialize the ring buffer with a fixed size."""
        self.size = size
        self.buffer = array.array('I', [0] * size)  # Unsigned integers array
        self.head = 0  # Points to the oldest element
        self.tail = 0  # Points to the next write position
        self.is_full = False  # Indicates if the buffer is full

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


# # Example usage:
# buffer = RingBuffer(5)

# # Adding values to the buffer
# buffer.append(10)
# buffer.append(20)
# buffer.append(30)
# buffer.append(40)
# buffer.append(50)

# # The buffer is full now, so adding more will overwrite the oldest value
# buffer.append(60)  # Overwrites 10
# buffer.append(70)  # Overwrites 20

# # Calculate average of the current values in the buffer
# average = buffer.calculate_average()
# print(f"Average: {average}")  # Should print the average of [30, 40, 50, 60, 70]
