import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ResponseComponent } from '../models/api.models';

@Component({
  selector: 'app-bar-chart',
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="component-block">
      <h3>{{ component.title }}</h3>
      <p class="empty-state" *ngIf="!hasData">No data available for this view.</p>
      <div class="bar-chart" *ngIf="hasData">
        <div class="bar-row" *ngFor="let item of data">
          <span>{{ item[labelKey] }}</span>
          <div><i [style.width.%]="width(item)"></i></div>
          <strong>{{ formatValue(item[valueKey]) }}</strong>
        </div>
      </div>
    </section>
  `
})
export class BarChartComponent {
  @Input({ required: true }) component!: ResponseComponent;

  get data(): Record<string, unknown>[] {
    return this.component.data || [];
  }

  get labelKey(): string {
    return this.component.x_key || 'label';
  }

  get valueKey(): string {
    return this.component.y_key || 'value';
  }

  get hasData(): boolean {
    return this.data.length > 0 && this.data.some((row) => row[this.labelKey] !== undefined && row[this.valueKey] !== undefined);
  }

  /** Scales one bar against the largest visible value in the chart. */
  width(item: Record<string, unknown>): number {
    const max = Math.max(...this.data.map((row) => Number(row[this.valueKey]) || 0), 1);
    return ((Number(item[this.valueKey]) || 0) / max) * 100;
  }

  get isMoneyChart(): boolean {
    return ['rent', 'loss', 'balance', 'amount', 'charge'].some((token) => this.valueKey.includes(token));
  }

  /** Formats chart values as dollars only for money metrics. */
  formatValue(value: unknown): string {
    const number = Number(value) || 0;
    if (this.isMoneyChart) {
      return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(number);
    }
    return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(number);
  }
}
