import { demoScorecardsEnabled } from '../../lib/demoLogin'

export const draftLayers = {
  layer1: 'Layer 1 policies',
  layer2: 'Layer 2 drafts',
  other: 'Other drafts',
} as const

export type DraftLayer = keyof typeof draftLayers

// Match original questions so display labels survive database reseeding.
// The stored questions and versioned content still drive review decisions.
const draftLabels: Record<string, readonly [DraftLayer, string]> = {
  'How should an agent answer a product question when the FAQ lacks the detail?':
    ['layer1', 'Product details, care and warranty'],
  'How should an agent answer whether a specific size is in stock or coming back?':
    ['layer1', 'Stock and restocks'],
  'What must an agent check before quoting a price, promotion, delivery estimate or service fee?':
    ['layer1', 'Prices, offers and delivery'],
  'How should an agent explain membership qualification, account changes or payment restrictions?':
    ['layer1', 'Membership and account eligibility'],
  'How should an agent describe a requested action when a prerequisite is still pending?':
    ['layer1', 'Actions pending verification'],

  'When should an Agent open Search FAQ for a product question?':
    ['layer2', 'FAQ search for product questions'],
  "How does the order's shipping status affect a shipping-fee request?":
    ['layer2', 'Shipping fee waivers and refunds'],
  'When can a customer upgrade an order to overnight shipping?':
    ['layer2', 'Overnight shipping upgrades'],
  'What applies when a customer requests a return for the wrong colour?':
    ['layer2', 'Returns for wrong colour'],
  'What applies when a customer requests a return because of fit?':
    ['layer2', 'Returns for poor fit'],
  'What troubleshooting options apply to a cart that fails to update?':
    ['layer2', 'Fixing cart update issues'],
  'What should an Agent do when yesterday’s price was lower?':
    ['layer2', 'Previous-day prices'],
  'What is the typical duration when a promo code is rejected?':
    ['layer2', 'Promo code expiry'],
  'What information is needed for each initial refund method?':
    ['layer2', 'Refund methods'],
  'How is the amount calculated when an item is added to an existing refund?':
    ['layer2', 'Adding items to a refund'],
  'What troubleshooting options can the Agent suggest when site search fails?':
    ['layer2', 'Fixing site search'],
  'How should an Agent handle an ineligible subscription extension?':
    ['layer2', 'Ineligible subscription extensions'],
  'How should an Agent handle an eligible Gold subscription extension?':
    ['layer2', 'Gold subscription extensions'],
}

export function draftPresentation(originalTitle: string, layer?: DraftLayer | null): { title: string; layer: DraftLayer } {
  const match = Object.hasOwn(draftLabels, originalTitle)
    ? draftLabels[originalTitle]
    : undefined
  const displayLayer = layer ?? (demoScorecardsEnabled() ? match?.[0] : undefined) ?? 'other'
  return { title: match?.[1] ?? originalTitle, layer: displayLayer }
}

const topicLabels = new Map([
  ['Adding an item to a refund', 'Refunds'],
  ['Cart not updating', 'Website'],
  ['Initial refund methods', 'Refunds'],
  ['Membership and account eligibility', 'Membership'],
  ['Overnight shipping upgrade', 'Shipping'],
  ['Pending verification, waivers and refunds', 'Verification'],
  ['Price increase since yesterday', 'Pricing'],
  ['Prices, promotions, delivery and paid options', 'Pricing'],
  ['Product information and care', 'Products'],
  ['Product specifications, care and warranty', 'Products'],
  ['Return due to colour', 'Returns'],
  ['Return due to size', 'Returns'],
  ['Shipping fee waiver or partial refund', 'Shipping'],
  ['Site search troubleshooting', 'Website'],
  ['Stock and restock answers', 'Stock'],
  ['Subscriptions and membership', 'Membership'],
  ['Typical promo-code duration', 'Promotions'],
])

export function draftTopic(topic: string) {
  return topicLabels.get(topic) ?? topic
}
