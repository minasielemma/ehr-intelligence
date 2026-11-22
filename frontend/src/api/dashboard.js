/**
 * Dashboard & Health API service.
 */
import { apiRequest } from "./client.js";

export async function getDashboardStats() {
    return await apiRequest("/dashboard/stats");
}

export async function getSystemHealth() {
    return await apiRequest("/health");
}
