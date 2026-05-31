import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Property } from '../models/api.models';

@Component({
  selector: 'app-property-selector',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <label class="control-label" for="property">Property</label>
    <select id="property" class="control" [ngModel]="selected" (ngModelChange)="selectedChange.emit($event)">
      <option *ngFor="let property of properties" [value]="property.property_code">
        {{ property.property_code }} - {{ property.property_name || property.official_property_name || 'Unnamed property' }}
      </option>
    </select>
  `
})
export class PropertySelectorComponent {
  @Input({ required: true }) properties: Property[] = [];
  @Input({ required: true }) selected = '';
  /** Emits active property changes so the parent can reset chat scope. */
  @Output() selectedChange = new EventEmitter<string>();
}
