package com.acme.payments.api;

public interface PaymentsClient {
    void requestPayment(String orderId, long amount);
}
