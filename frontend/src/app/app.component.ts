import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { forkJoin } from 'rxjs';
import { ApiService } from './services/api.service';
import { ChatMessage, Diagnostics, Property } from './models/api.models';
import { PropertySelectorComponent } from './components/property-selector.component';
import { ModelSelectorComponent } from './components/model-selector.component';
import { ChatComponent } from './components/chat.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, PropertySelectorComponent, ModelSelectorComponent, ChatComponent],
  template: `
    <main class="app-shell">
      <aside class="sidebar">
        <header>
          <span class="eyebrow">Asset AI</span>
          <h1>Asset AI</h1>
          <p>Property-scoped intelligence for multifamily operations</p>
        </header>

        <section class="controls">
          <app-property-selector
            [properties]="properties"
            [selected]="propertyCode"
            (selectedChange)="setProperty($event)">
          </app-property-selector>

          <app-model-selector
            [models]="models"
            [selected]="selectedModel"
            (selectedChange)="selectedModel = $event">
          </app-model-selector>
        </section>

        <section class="property-card" *ngIf="activeProperty">
          <h2>{{ activeProperty.property_name || activeProperty.official_property_name || activeProperty.property_code }}</h2>
          <div class="availability-badges">
            <span [class.available]="activeProperty.has_rent_roll_snapshots">
              {{ activeProperty.has_rent_roll_snapshots ? 'Rent roll available' : 'No rent roll data' }}
            </span>
            <span [class.available]="activeProperty.has_website_pages">
              {{ activeProperty.has_website_pages ? 'Website available' : 'No website pages' }}
            </span>
          </div>
          <p>{{ activeProperty.address || 'No address loaded yet' }}</p>
          <a *ngIf="activeProperty.website_url" [href]="activeProperty.website_url" target="_blank" rel="noopener noreferrer">Open website</a>
        </section>

        <section class="diagnostics" *ngIf="diagnostics">
          <div><span>Properties</span><strong>{{ diagnostics.property_count }}</strong></div>
          <div><span>Rent-roll rows</span><strong>{{ diagnostics.rent_roll_row_count }}</strong></div>
          <div><span>Website pages</span><strong>{{ diagnostics.website_page_count }}</strong></div>
          <div><span>Chroma chunks</span><strong>{{ diagnostics.chroma_collection_status['count'] || 0 }}</strong></div>
        </section>
      </aside>

      <app-chat
        [messages]="messages"
        [loading]="loading"
        [propertyCode]="propertyCode"
        (send)="sendMessage($event)"
        (reset)="resetChat()">
      </app-chat>
    </main>
  `
})
export class AppComponent implements OnInit {
  properties: Property[] = [];
  diagnostics?: Diagnostics;
  propertyCode = '';
  selectedModel = 'gpt-4o-mini';
  models = ['gpt-4o-mini', 'gpt-4.1-mini', 'gpt-4o', 'gpt-4.1'];
  messages: ChatMessage[] = [];
  loading = false;
  sessionId = crypto.randomUUID();

  constructor(private readonly api: ApiService) {}

  /** Loads properties and diagnostics before initializing the scoped chat workspace. */
  ngOnInit(): void {
    forkJoin({
      properties: this.api.getProperties(),
      diagnostics: this.api.getDiagnostics()
    }).subscribe({
      next: ({ properties, diagnostics }) => {
        this.properties = properties;
        this.diagnostics = diagnostics;
        this.models = diagnostics.available_models?.length ? diagnostics.available_models : this.models;
        this.propertyCode = properties.find((item) => item.property_code === '115r')?.property_code || properties[0]?.property_code || '';
        this.resetChat();
      },
      error: () => {
        this.messages = [{
          role: 'assistant',
          content: 'I could not reach the Asset AI backend. Start FastAPI on `http://localhost:8000`, then refresh this page.'
        }];
      }
    });
  }

  get activeProperty(): Property | undefined {
    return this.properties.find((property) => property.property_code === this.propertyCode);
  }

  /** Switches the active property and resets chat history to avoid scope mixing. */
  setProperty(propertyCode: string): void {
    this.propertyCode = propertyCode;
    this.resetChat();
  }

  /** Starts a fresh session for the currently selected property. */
  resetChat(): void {
    this.sessionId = crypto.randomUUID();
    const name = this.activeProperty?.property_name || this.activeProperty?.official_property_name || this.propertyCode || 'a property';
    this.messages = [{
      role: 'assistant',
      content: `Hi, I'm Asset AI. I'm scoped to **${name}** and can help with rent-roll KPIs, lease risk, high balances, occupancy trends, advertised amenities, and management concerns.`
    }];
  }

  /** Sends a user message with the active property code and selected LLM model. */
  sendMessage(message: string): void {
    if (!this.propertyCode || this.loading) {
      return;
    }
    this.messages = [...this.messages, { role: 'user', content: message }];
    this.loading = true;
    this.api.chat(this.sessionId, this.propertyCode, message, this.selectedModel).subscribe({
      next: (response) => {
        this.messages = [...this.messages, { role: 'assistant', content: response.answer_markdown, response }];
        this.loading = false;
      },
      error: (error) => {
        const detail = error?.error?.detail || 'The backend could not complete the request.';
        this.messages = [...this.messages, { role: 'assistant', content: String(detail) }];
        this.loading = false;
      }
    });
  }
}
