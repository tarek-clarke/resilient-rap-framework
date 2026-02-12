# SemanticMatchReviewCard Component

A production-ready React component for human-in-the-loop review of AI-generated field name mappings in telemetry data pipelines. Built with TypeScript, Tailwind CSS, and Lucide React icons.

## Overview

The `SemanticMatchReviewCard` component enables users to review and approve/remap semantic field mappings from the benchmark-tested confidence thresholds (0.45 default). Perfect for telemetry pipelines processing hundreds of fields from different sensors and data sources.

## Features

✅ **Confidence-Based Visualization**
- Color-coded status badges (🔴 Critical < 0.45, 🟡 Warning 0.45-0.70, 🟢 Safe > 0.70)
- Visual confidence progress bar
- Clarity on benchmark thresholds

✅ **User-Friendly Interactions**
- Approve suggested mappings
- Remap to different schema fields
- Ignore fields entirely
- Supports dropdown or freeform text input

✅ **Responsive Design**
- Works on mobile (single column)
- Optimized for dashboard grids (2-3 columns on desktop)
- Tailwind CSS for consistent styling

✅ **Accessible**
- Semantic HTML
- ARIA labels for icons
- Disabled states with visual feedback
- Keyboard navigable

## Installation

### Prerequisites
```bash
npm install react lucide-react tailwindcss
# or
yarn add react lucide-react tailwindcss
```

### Component Import
```tsx
import { SemanticMatchReviewCard } from './SemanticMatchReviewCard';
```

## Props Interface

```typescript
interface SemanticMatchReviewCardProps {
  // Required
  incomingField: string;              // e.g., 'brk_tmp_fr'
  suggestedMatch: string | null;      // e.g., 'Brake Temperature' or null
  confidenceScore: number;            // 0.0 to 1.0, e.g., 0.65

  // Optional
  schemaOptions?: string[];           // Available schema fields for remapping
  onApprove?: (field: string, match: string) => void;
  onRemap?: (field: string, newMatch: string) => void;
  onIgnore?: (field: string) => void;
}
```

## Usage Examples

### Basic Usage
```tsx
import SemanticMatchReviewCard from './SemanticMatchReviewCard';

export default function ReviewPage() {
  return (
    <SemanticMatchReviewCard
      incomingField="hr_watch_01"
      suggestedMatch="Heart Rate (bpm)"
      confidenceScore={0.85}
      onApprove={(field, match) => {
        console.log(`${field} approved as ${match}`);
        // Submit to API
      }}
    />
  );
}
```

### With Schema Options (Dropdown Remap)
```tsx
const SCHEMA = [
  'Heart Rate (bpm)',
  'Brake Temperature (Celsius)',
  'Engine RPM',
  // ... more fields
];

<SemanticMatchReviewCard
  incomingField="car_velocity"
  suggestedMatch="Vehicle Speed (km/h)"
  confidenceScore={0.65}
  schemaOptions={SCHEMA}
  onRemap={(field, newMatch) => {
    updateMapping(field, newMatch);
  }}
/>
```

### Dashboard with Multiple Cards
```tsx
import { useState } from 'react';

export function SemanticReviewDashboard() {
  const [reviews, setReviews] = useState(fetchReviews());

  const handleApprove = (field, match) => {
    setReviews(prev => prev.filter(r => r.incomingField !== field));
    submitApproval(field, match);
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {reviews.map(review => (
        <SemanticMatchReviewCard
          key={review.id}
          incomingField={review.incomingField}
          suggestedMatch={review.suggestedMatch}
          confidenceScore={review.confidenceScore}
          schemaOptions={SCHEMA}
          onApprove={handleApprove}
          onIgnore={(field) => setReviews(prev => 
            prev.filter(r => r.incomingField !== field)
          )}
        />
      ))}
    </div>
  );
}
```

## Confidence Levels

The component uses a **0.45 threshold** based on semantic layer benchmark testing:

| Level | Score | Appearance | Use Case |
|-------|-------|-----------|----------|
| 🔴 Critical | < 0.45 | Red badge, red progress bar | Heavily abbreviated or obscure names (e.g., `hr_watch_01`) |
| 🟡 Warning | 0.45 - 0.70 | Yellow badge, yellow progress bar | Alternative terminology or partial matches (e.g., `car_velocity`) |
| 🟢 Safe | > 0.70 | Green badge, green progress bar | High-confidence matches (e.g., `steering_angle_weird` → Steering Angle) |

## Styling Customization

The component uses Tailwind CSS utility classes. To customize colors:

1. **Modify badge colors** in `badgeConfig`:
```tsx
const badgeConfig = {
  critical: {
    bgColor: 'bg-red-50',
    textColor: 'text-red-700',
    borderColor: 'border-red-200',
    badgeBg: 'bg-red-100',
    badgeText: 'text-red-800',
  },
  // ...
};
```

2. **Use Tailwind CSS config** for consistent theming:
```js
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      colors: {
        'semantic-critical': '#ef4444',
        'semantic-warning': '#eab308',
        'semantic-safe': '#22c55e',
      }
    }
  }
};
```

## Accessibility

- ✅ Semantic HTML structure
- ✅ Disabled states are styled and non-interactive
- ✅ Lucide icons provide visual indicators
- ✅ Tooltips on disabled "Approve" button when no suggestion available
- ✅ Clear, readable color contrast (WCAG AA)
- ✅ Keyboard navigable buttons

## Performance

- **Re-renders**: Optimized with React.memo if needed for large grids
- **Icons**: Lucide React provides tree-shakeable SVG icons (minimal bundle impact)
- **Styling**: Tailwind CSS classes (no runtime CSS generation)
- **State**: Local component state only (no external state management needed)

## Real-World Integration

### API Integration Pattern
```tsx
async function submitReview(action: 'approve' | 'remap' | 'ignore', field: string, newMatch?: string) {
  const response = await fetch('/api/telemetry/mappings/review', {
    method: 'POST',
    body: JSON.stringify({
      action,
      incomingField: field,
      finalMatch: newMatch || null,
    })
  });
  return response.json();
}

// In component:
onApprove={async (field, match) => {
  await submitReview('approve', field, match);
  // Update UI
}}
```

### Batch Processing
```tsx
const [selectedReviews, setSelectedReviews] = useState<Set<string>>(new Set());

// Approve all 'safe' confidence scores at once
const approveSafeMatches = () => {
  reviews
    .filter(r => r.confidenceScore > 0.70)
    .forEach(r => {
      handleApprove(r.incomingField, r.suggestedMatch!);
    });
};
```

## Testing

```tsx
import { render, screen, userEvent } from '@testing-library/react';
import SemanticMatchReviewCard from './SemanticMatchReviewCard';

describe('SemanticMatchReviewCard', () => {
  it('renders with high confidence (green)', () => {
    render(
      <SemanticMatchReviewCard
        incomingField="test"
        suggestedMatch="Test Field"
        confidenceScore={0.85}
      />
    );
    expect(screen.getByText('High Confidence')).toBeInTheDocument();
  });

  it('disables approve button when no suggested match', () => {
    render(
      <SemanticMatchReviewCard
        incomingField="test"
        suggestedMatch={null}
        confidenceScore={0.3}
      />
    );
    expect(screen.getByText('Approve')).toBeDisabled();
  });

  it('calls onIgnore when ignore button clicked', async () => {
    const onIgnore = jest.fn();
    render(
      <SemanticMatchReviewCard
        incomingField="test"
        suggestedMatch="Match"
        confidenceScore={0.5}
        onIgnore={onIgnore}
      />
    );
    await userEvent.click(screen.getByText('Ignore'));
    expect(onIgnore).toHaveBeenCalledWith('test');
  });
});
```

## Troubleshooting

### Tailwind CSS Not Applied
- Ensure Tailwind CSS is properly configured in your project
- Verify `content` in `tailwind.config.js` includes this component's path
- Rebuild CSS: `npm run build:css`

### Icons Not Showing
- Verify `lucide-react` is installed: `npm install lucide-react`
- Check that icons are imported correctly

### Dropdown Not Showing Options
- Pass `schemaOptions` prop to enable dropdown mode
- Without `schemaOptions`, component shows text input field

## Performance Benchmarks

Based on semantic layer testing:
- **Card render time**: < 5ms
- **Confidence calculation**: < 1ms
- **Suitable for**: 100+ cards in grid view on modern browsers

## Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- Requires React 16.8+ (hooks)

## License

Licensed under PolyForm Noncommercial License 1.0.0

## Related Components

- `SemanticTranslator` - Backend semantic matching engine
- `SemanticReviewDashboard` - Full dashboard implementation (see examples)

## Contributing

When modifying this component:
1. Update TypeScript interfaces in `Props`
2. Add test cases for new features
3. Update this documentation
4. Maintain Tailwind CSS utility usage (no inline styles)
5. Keep component pure (no external API calls in component)

---

**Last Updated**: February 11, 2026  
**Component Version**: 1.0.0  
**React Version**: 18.0+  
**Tailwind CSS**: 3.0+
