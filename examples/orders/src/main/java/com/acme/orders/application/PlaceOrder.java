package com.acme.orders.application;

import com.acme.orders.domain.Order;
import com.acme.payments.api.PaymentsClient;

public class PlaceOrder {
    public Order run() { return new Order(); }
}
