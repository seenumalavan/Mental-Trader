from enum import Enum

class Product(Enum):
    I = "I"  # Intraday (MIS - Margin Intraday Square-off)
    D = "D"  # Delivery (CNC - Cash and Carry)
    CO = "CO"  # Cover Order
    NRML = "NRML"  # Normal (for derivatives, no leverage)

class Validity(Enum):
    DAY = "DAY"  # Order valid for the entire trading day
    IOC = "IOC"  # Immediate or Cancel (executes immediately or gets cancelled)