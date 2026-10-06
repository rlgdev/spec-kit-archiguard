package com.acme.orders.api;

import com.acme.orders.application.PlaceOrder;
import com.acme.payments.internal.PaymentGateway;   // ARCH-301: payments publishes only com.acme.payments.api

@RestController
public class OrderController {
    @PostMapping("/orders")
    public Order place() { return new PlaceOrder().run(); }

    @GetMapping("/orders/{orderId}")
    public Order read(String orderId) { return null; }
}
