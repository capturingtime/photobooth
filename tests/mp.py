# Works
from multiprocessing import Process, Manager, Lock
# from multiprocessing.managers import Value
# from multiprocessing import Value
from ctypes import c_wchar_p

class Component():
    def __init__(self):
        self._test = Manager().Value(c_wchar_p, "True")  # Works
        # self._test = Value(c_wchar_p, "True", lock=Lock())  # Doesn't Work
        # self._test = Value('d', 5.0, lock=Lock())  # Works
    def run(self):
        print(f"Memory Address before change: {self._test}")
        print(f"Value in Thread Before: {self._test.value}")
        self._test.value = "False"
        # self._test.value = 6.0
        print(f"Memory Address after change: {self._test}")
        print(f"Value in Thread After: {self._test.value}")

if __name__ == '__main__':

    c = Component()
    p = Process(target=c.run)

    print(f"Memory Address of original: {c._test}")
    print(f"Value Before: {c._test.value}")

    p.start()
    p.join()
    p.close()

    print(f"Memory Address: {c._test}")
    print(f"Value After: {c._test.value}")

"""
>>> from multiprocessing import Process, Manager, Lock
>>> from ctypes import c_wchar_p
>>> class Component():
...     def __init__(self):
...         self._test = Manager().Value(c_wchar_p, "True")  # Works
...     def run(self):
...         print(f"Memory Address before change: {self._test}")
...         print(f"Value in Thread Before: {self._test.value}")
...         self._test.value = "False"
...         print(f"Memory Address after change: {self._test}")
...         print(f"Value in Thread After: {self._test.value}")
...
>>> c = Component()
>>> p = Process(target=c.run)
>>> print(f"Memory Address of original: {c._test}")
Memory Address of original: Value(<class 'ctypes.c_wchar_p'>, 'True')
>>> print(f"Value Before: {c._test.value}")
Value Before: True
>>> p.start()
>>> Memory Address before change: Value(<class 'ctypes.c_wchar_p'>, 'True')
Value in Thread Before: True
Memory Address after change: Value(<class 'ctypes.c_wchar_p'>, 'False')
Value in Thread After: False
>>> p.join()
>>> p.close()
>>>
>>> print(f"Memory Address: {c._test}")
Memory Address: Value(<class 'ctypes.c_wchar_p'>, 'False')
>>> print(f"Value After: {c._test.value}")
Value After: False

"""
