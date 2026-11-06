const { test } = require('node:test');
const assert = require('node:assert/strict');
const core = require('../core.js');

test('profile projection keeps only documented facts and explicit booleans', () => {
  const profile = core.sanitizeProfile({
    first_name: 'Ada',
    email: 'ada@example.test',
    work_authorized: 'yes',
    requires_sponsorship: false,
    token: 'secret',
    experience: [{ company: 'Example', title: 'Engineer', password: 'secret' }],
    education: [{ institution: 'Example University', gpa: '3.8', secret: 'x' }],
  });
  assert.equal(profile.first_name, 'Ada');
  assert.equal(profile.work_authorized, null);
  assert.equal(profile.requires_sponsorship, false);
  assert.equal(profile.token, undefined);
  assert.deepEqual(profile.experience, [{ company: 'Example', title: 'Engineer' }]);
  assert.deepEqual(profile.education, [{ institution: 'Example University', gpa: '3.8' }]);
});

test('matches semantic labels and autocomplete without guessing unknown questions', () => {
  assert.equal(
    core.inferField({ label: 'Given name', autocomplete: 'given-name' }).key,
    'first_name',
  );
  assert.equal(core.inferField({ label: 'LinkedIn profile URL' }).key, 'linkedin');
  assert.equal(core.inferField({ label: 'Postal / ZIP code' }).key, 'postal_code');
  assert.equal(core.inferField({ label: 'Why do you want to work here?' }).key, null);
  assert.equal(core.inferField({ label: 'Manager email address' }).key, null);
  assert.equal(core.inferField({ label: 'Emergency contact phone' }).key, null);
  assert.equal(
    core.inferField({ label: 'What is your preferred interview language?', autocomplete: 'email' })
      .key,
    null,
  );
  assert.equal(core.inferField({ name: 'field_42', autocomplete: 'email' }).key, 'email');
});

test('authorization and sponsorship retain question polarity', () => {
  assert.deepEqual(
    core.inferField({ label: 'Are you legally authorized to work in the United States?' }),
    { key: 'work_authorized', invert: false },
  );
  assert.deepEqual(
    core.inferField({ label: 'Will you require visa sponsorship now or in the future?' }),
    { key: 'requires_sponsorship', invert: false },
  );
  assert.deepEqual(core.inferField({ label: 'Can you work without sponsorship?' }), {
    key: 'requires_sponsorship',
    invert: true,
  });
  assert.equal(core.inferField({ label: 'Are you not authorized to work?' }).key, null);
  assert.equal(
    core.inferField({ label: 'Do you have authorization and need sponsorship?' }).key,
    null,
  );
  for (const label of [
    'Does your spouse have work authorization?',
    'Have you ever lost work authorization?',
    'Are you unwilling to relocate?',
    'Do you refuse relocation?',
    'Are you willing to relocate and travel?',
  ])
    assert.equal(core.inferField({ label }).key, null, label);
});

test('legal authorization never answers attestations or scheduling eligibility', () => {
  for (const label of [
    'Do you attest you are authorized to work in the United States?',
    'Do you certify that you are legally authorized to work?',
    'Do you acknowledge that you are legally authorized to work?',
  ])
    assert.equal(core.inferField({ label }).blocked, true, label);
  for (const label of [
    'Are you eligible to work nights and weekends?',
    'Are you authorized to work overtime?',
    'Are you eligible to work with children?',
    'Are you legally authorized to work and available for night shifts?',
  ])
    assert.equal(core.inferField({ label }).key, null, label);
  assert.equal(
    core.inferField({ label: 'Are you legally eligible to work?' }).key,
    'work_authorized',
  );
  assert.equal(
    core.inferField({ label: 'Do you have work authorization?' }).key,
    'work_authorized',
  );
});

test('contact fields for supervisors and other people never use applicant facts', () => {
  for (const context of [
    'Supervisor information',
    'Spouse details',
    'Parent information',
    'Recruiter contact',
    'Emergency contact',
    'Reference 1',
    'References',
    'Referees',
    'Supervisors',
    'Managers',
    'Recruiters',
    'Parents',
    'Spouses',
    'Emergency contacts',
  ])
    for (const label of ['Name', 'Email address', 'Phone number'])
      assert.equal(core.inferField({ label, context }).key, null, `${context}: ${label}`);
  assert.equal(
    core.inferField({ label: 'Company', context: 'Employment 1' }).key,
    'experience.company',
  );
});

test('sensitive, demographic, attestation and credential controls are blocked even with misleading autocomplete', () => {
  for (const label of [
    'Social security number',
    'National ID',
    'Credit card number',
    'Date of birth',
    'Gender',
    'Ethnicity',
    'I certify my email is accurate',
    'I agree to terms',
    'Reference email',
    'Password',
    'Passport number',
    'Cardholder name',
    'I acknowledge the information above',
    'Electronic signature',
    'Payment account name',
  ]) {
    assert.equal(core.inferField({ label, autocomplete: 'email' }).blocked, true, label);
  }
  assert.equal(core.inferField({ label: 'Contact', type: 'password' }).blocked, true);
});

test('native select matching is exact or a known country/state alias, never partial', () => {
  const options = [
    { value: '', label: 'Choose' },
    { value: 'US', label: 'United States' },
    { value: 'GB', label: 'United Kingdom' },
  ];
  assert.equal(core.selectOption(options, 'United States', 'country'), 'US');
  assert.equal(core.selectOption(options, 'USA', 'country'), 'US');
  assert.equal(
    core.selectOption([{ value: 'CA', label: 'California' }], 'California', 'state'),
    'CA',
  );
  assert.equal(core.selectOption(options, 'United', 'country'), null);
  assert.equal(
    core.selectOption(
      [
        { value: 'y', label: 'Yes' },
        { value: 'n', label: 'No' },
      ],
      false,
    ),
    'n',
  );
  assert.equal(
    core.selectOption([{ value: 'yes', label: 'Yes, I agree to receive marketing emails' }], true),
    null,
  );
});

test('history needs explicit context; broad start dates and ambiguous years stay unanswered', () => {
  assert.equal(
    core.inferField({ label: 'Company', context: 'Employment 1' }).key,
    'experience.company',
  );
  assert.equal(
    core.inferField({ label: 'Start date', context: 'Education 1' }).key,
    'education.start',
  );
  assert.equal(core.inferField({ label: 'Start date' }).key, null);
  assert.equal(core.inferField({ label: 'Years' }).key, null);
  assert.equal(
    core.inferField({ label: 'Years of professional experience' }).key,
    'years_experience',
  );
});

test('resume validation enforces type, size and real file signatures', () => {
  assert.equal(core.validateResume({ name: 'resume.pdf', size: 10 }, [37, 80, 68, 70, 45]), null);
  assert.match(
    core.validateResume({ name: 'resume.pdf', size: 5242881 }, [37, 80, 68, 70, 45]),
    /5 MiB/,
  );
  assert.match(core.validateResume({ name: 'resume.exe', size: 10 }, [77, 90]), /PDF or DOCX/);
  assert.match(core.validateResume({ name: 'resume.pdf', size: 10 }, [77, 90]), /contents/);
});
