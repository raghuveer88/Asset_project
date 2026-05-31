import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { ChatResponse, Diagnostics, Property } from '../models/api.models';
import { environment } from '../../environments/environment';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly baseUrl = environment.apiBaseUrl;

  constructor(private readonly http: HttpClient) {}

  /** Loads property metadata for the global property selector. */
  getProperties(): Observable<Property[]> {
    return this.http.get<Property[]>(`${this.baseUrl}/properties`);
  }

  /** Fetches latest scoped analytics for the selected property. */
  getOverview(propertyCode: string): Observable<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>(`${this.baseUrl}/properties/${propertyCode}/overview`);
  }

  /** Loads backend health, row counts, model allow-list, and Chroma status. */
  getDiagnostics(): Observable<Diagnostics> {
    return this.http.get<Diagnostics>(`${this.baseUrl}/diagnostics`);
  }

  /** Sends a chat turn with the active property and selected runtime model. */
  chat(sessionId: string, propertyCode: string, message: string, selectedModel: string): Observable<ChatResponse> {
    return this.http.post<ChatResponse>(`${this.baseUrl}/chat`, {
      session_id: sessionId,
      property_code: propertyCode,
      message,
      selected_model: selectedModel
    });
  }
}
