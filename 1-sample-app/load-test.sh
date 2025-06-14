#!/bin/bash

echo "Scaling up log generator..."
kubectl scale deployment log-generator-app --replicas=10

echo "Waiting for pods to be ready..."
kubectl wait --for=condition=ready pod -l app=log-generator --timeout=120s

echo "Running load test for 10 minutes..."
sleep 600

echo "Scaling down..."
kubectl scale deployment log-generator-app --replicas=3

echo "Load test completed."
