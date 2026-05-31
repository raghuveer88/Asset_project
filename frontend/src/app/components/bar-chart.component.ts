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
        <div class="bar-row" *ngFor="let item of chartRows" [class.negative]="item.isNegative">
          <span>{{ item.label }}</span>
          <div><i [style.width.%]="item.widthPercent"></i></div>
          <strong>{{ formatValue(item.rawValue) }}</strong>
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

  get chartRows(): { label: unknown; rawValue: number; widthPercent: number; isNegative: boolean }[] {
    const maxAbs = Math.max(...this.data.map((row) => Math.abs(this.numericValue(row[this.valueKey]))), 1);
    return this.data.map((row) => {
      const rawValue = this.numericValue(row[this.valueKey]);
      return {
        label: row[this.labelKey],
        rawValue,
        widthPercent: (Math.abs(rawValue) / maxAbs) * 100,
        isNegative: rawValue < 0
      };
    });
  }

  get isMoneyChart(): boolean {
    return ['rent', 'loss', 'balance', 'amount', 'charge'].some((token) => this.valueKey.includes(token));
  }

  /** Formats chart values as dollars only for money metrics. */
  formatValue(value: unknown): string {
    const number = this.numericValue(value);
    if (this.isMoneyChart) {
      return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(number);
    }
    return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(number);
  }

  private numericValue(value: unknown): number {
    const number = Number(value);
    return Number.isFinite(number) ? number : 0;
  }
}
