import { Component } from '@angular/core';

@Component({
  selector: 'app-loading-state',
  standalone: true,
  template: `
    <div class="loading-state">
      <span></span><span></span><span></span>
    </div>
  `
})
export class LoadingStateComponent {}
