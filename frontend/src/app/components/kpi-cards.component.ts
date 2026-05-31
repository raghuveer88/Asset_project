import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ResponseComponent } from '../models/api.models';

@Component({
  selector: 'app-kpi-cards',
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="component-block">
      <h3>{{ component.title }}</h3>
      <p class="empty-state" *ngIf="!hasData">No data available for this view.</p>
      <div class="kpi-grid" *ngIf="hasData">
        <article class="kpi" *ngFor="let item of component.data || []">
          <span>{{ item['label'] }}</span>
          <strong>{{ item['value'] }}</strong>
          <small>{{ item['description'] }}</small>
        </article>
      </div>
    </section>
  `
})
export class KpiCardsComponent {
  @Input({ required: true }) component!: ResponseComponent;

  get hasData(): boolean {
    return !!this.component.data?.length;
  }
}
