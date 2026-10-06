# Data Model: Place an order

### Order

- id, customerId, lines (OrderLine[]), total, status

### OrderLine

- sku, quantity, price

### PaymentRequest

- orderId, amount (sent to the payments context)

### Shipment

- orderId, address (a term the orders glossary does not know - A0.4 reports it)
