(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.JobPilotCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const TEXT_FIELDS = [
    'name',
    'first_name',
    'last_name',
    'email',
    'phone',
    'location',
    'address_line1',
    'address_line2',
    'city',
    'state',
    'postal_code',
    'country',
    'linkedin',
    'website',
    'github',
    'portfolio',
    'current_employer',
    'current_title',
    'salary_expectation',
    'salary_currency',
    'available_date',
    'years_experience',
  ];
  const BOOLEAN_FIELDS = ['work_authorized', 'requires_sponsorship', 'willing_to_relocate'];
  const LIST_FIELDS = ['skills', 'certifications', 'interests'];
  const RECORD_FIELDS = {
    experience: ['company', 'title', 'start', 'end', 'location', 'description'],
    education: ['institution', 'degree', 'field_of_study', 'start', 'end', 'gpa'],
  };
  const MAX_BYTES = 5 * 1024 * 1024;
  function normalize(value) {
    return String(value ?? '')
      .replace(/([a-z])([A-Z])/g, '$1 $2')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, ' ')
      .trim()
      .replace(/\s+/g, ' ');
  }
  function sanitizeProfile(input) {
    if (!input || typeof input !== 'object' || Array.isArray(input))
      throw new Error('Profile must be a JSON object.');
    const result = {};
    for (const key of TEXT_FIELDS)
      if (typeof input[key] === 'string' || typeof input[key] === 'number')
        result[key] = String(input[key]).trim().slice(0, 12000);
    for (const key of BOOLEAN_FIELDS)
      result[key] = typeof input[key] === 'boolean' ? input[key] : null;
    for (const key of LIST_FIELDS) {
      if (Array.isArray(input[key]))
        result[key] = input[key]
          .filter((v) => typeof v === 'string')
          .map((v) => v.trim().slice(0, 1000))
          .filter(Boolean)
          .slice(0, 200);
      else if (typeof input[key] === 'string')
        result[key] = input[key]
          .split(/[,\n]/)
          .map((v) => v.trim())
          .filter(Boolean)
          .slice(0, 200);
    }
    for (const [key, fields] of Object.entries(RECORD_FIELDS))
      if (Array.isArray(input[key]))
        result[key] = input[key]
          .slice(0, 50)
          .filter((record) => record && typeof record === 'object' && !Array.isArray(record))
          .map((record) =>
            Object.fromEntries(
              fields
                .filter(
                  (field) => typeof record[field] === 'string' || typeof record[field] === 'number',
                )
                .map((field) => [field, String(record[field]).trim().slice(0, 12000)]),
            ),
          );
    return result;
  }
  const BLOCKED =
    /\b(password|passcode|security code|social security|ssn|national id|national identification|tax id|passport|driver s license|credit card|debit card|card number|cardholder|card holder|payment|cvv|cvc|bank account|account number|routing number|iban|date of birth|birth date|dob|gender|sex|ethnicity|race|racial|religion|veteran|disability|disabled|pronouns|marital|sexual orientation|demographic|citizenship|citizen|i certify|certify that|certification of|i attest|attestation|i agree|i accept|i acknowledge|acknowledgement|i confirm|i understand|signature|consent|terms|privacy policy|background check|reference|referee|emergency contact)\b/;
  const ATTESTATION =
    /\b(attest|attests|attested|attesting|attestation|certify|certifies|certified|acknowledge|acknowledges|acknowledged|agree|agrees|agreed|accept|accepts|accepted)\b/;
  const OTHER_PERSON =
    /\b(managers?|supervisors?|recruiters?|parents?|spouses?|references?|referees?|emergency\s*contacts?)\b/;
  const AUTOCOMPLETE = {
    name: 'name',
    'given-name': 'first_name',
    'family-name': 'last_name',
    email: 'email',
    tel: 'phone',
    'street-address': 'address_line1',
    'address-line1': 'address_line1',
    'address-line2': 'address_line2',
    'address-level2': 'city',
    'address-level1': 'state',
    'postal-code': 'postal_code',
    country: 'country',
    'country-name': 'country',
    organization: 'current_employer',
    'organization-title': 'current_title',
    url: 'website',
  };
  function inferField(descriptor) {
    const { label = '', name = '', context = '', type = '', autocomplete = '' } = descriptor;
    const all = normalize(`${label} ${name} ${context} ${autocomplete}`);
    if (
      BLOCKED.test(all) ||
      ATTESTATION.test(all) ||
      /^(password|hidden|submit|button|reset|image|range|color)$/i.test(type)
    )
      return { key: null, blocked: true };
    // Context identifies whose answer is being requested, including otherwise
    // ordinary Name/Email/Phone labels inside a supervisor or spouse fieldset.
    if (OTHER_PERSON.test(all)) return { key: null };
    const text = normalize(label || name)
      .replace(/\b(required|optional)\b/g, '')
      .trim();
    const work =
      /\b(work authori[sz]ation|authori[sz]ed to work|work authori[sz]ed|right to work|legally eligible to work|legally permitted to work)\b/.test(
        text,
      );
    if (
      work &&
      /\b(night|nights|weekend|weekends|shift|shifts|overtime|hours|evening|evenings|schedule|travel|onsite|remote|hybrid|holiday|holidays)\b/.test(
        text,
      )
    )
      return { key: null };
    const sponsor = /\bsponsor(?:ship|ed|ing)?\b/.test(text);
    if (
      (work || sponsor || /\b(relocate|relocation)\b/.test(text)) &&
      /\b(manager|supervisor|recruiter|parent|spouse|employer|ever|lost|revoked|expired|unable)\b/.test(
        text,
      )
    )
      return { key: null };
    if (sponsor && /\b(authori[sz](?:ed|ation)|right to work|eligible to work)\b/.test(text))
      return { key: null };
    if (sponsor) {
      if (/\b(without|no sponsorship)\b/.test(text) && /\b(can|able|work)\b/.test(text))
        return { key: 'requires_sponsorship', invert: true };
      if (/\b(not|never|without|no|don t|doesn t)\b/.test(text)) return { key: null };
      if (/\b(need|require|requires|required|requiring)\b/.test(text))
        return { key: 'requires_sponsorship', invert: false };
      return { key: null };
    }
    if (work)
      return /\b(not|never|without|no|don t)\b/.test(text)
        ? { key: null }
        : { key: 'work_authorized', invert: false };
    if (/\b(relocat|relocate|relocation)\b/.test(text))
      return /\b(not|never|unwilling|refuse|and|or)\b/.test(text)
        ? { key: null }
        : { key: 'willing_to_relocate', invert: false };
    // A label referring to somebody else must not be rescued by autocomplete.
    if (
      /\b(manager|supervisor|recruiter|parent|spouse|former|previous)\b/.test(text) &&
      !/\b(employment|experience)\b/.test(normalize(context))
    )
      return { key: null };
    const history = /\b(education|academic|university|college)\b/.test(normalize(context))
      ? 'education'
      : /\b(employment|experience|work history|employer)\b/.test(normalize(context))
        ? 'experience'
        : null;
    if (history) {
      const mappings =
        history === 'experience'
          ? {
              company: /^(company|employer|company name|employer name)$/,
              title: /^(job title|position|title|role)$/,
              location: /^(location|work location)$/,
              description: /^(description|responsibilities|job description|role description)$/,
            }
          : {
              institution: /^(school|school name|university|college|institution|institution name)$/,
              degree: /^(degree|degree type)$/,
              field_of_study: /^(major|field of study|discipline)$/,
              gpa: /^(gpa|grade point average)$/,
            };
      mappings.start = /^(start|start date|from|date started|start year)$/;
      mappings.end = /^(end|end date|to|date ended|end year|graduation date|graduation year)$/;
      for (const [key, pattern] of Object.entries(mappings))
        if (pattern.test(text)) return { key: `${history}.${key}` };
    }
    const simple = {
      first_name: /^(your )?(first name|given name|forename)$/,
      last_name: /^(your )?(last name|family name|surname)$/,
      name: /^(your )?(full name|legal name|name)$/,
      email: /^(your )?(email|e mail)( address)?$/,
      phone: /^(your )?(phone|telephone|mobile|cell)( number)?$/,
      address_line1:
        /^(your )?(street address|address|address line 1|address 1|street address line 1)$/,
      address_line2: /^(address line 2|address 2|apartment|apt|suite|unit)( number)?$/,
      city: /^(city|town|city town)$/,
      state: /^(state|province|state province|region)$/,
      postal_code: /^(postal|zip|postal zip|zip postal)( code)?$/,
      country: /^(country|country region|country of residence)$/,
      location: /^(your )?(location|current location|home location)$/,
      linkedin: /^(linkedin|linked in)( profile)?( url| link)?$/,
      github: /^github( profile)?( url| link)?$/,
      portfolio: /^(portfolio|personal portfolio)( url| link)?$/,
      website: /^(website|personal website|personal site)( url| link)?$/,
      current_employer: /^(current employer|current company)$/,
      current_title: /^(current title|current job title|current position)$/,
      years_experience: /^(total )?years of (professional |relevant |work )?experience$/,
      salary_expectation:
        /^(salary expectation|salary expectations|expected salary|desired salary|salary requirement|salary requirements)$/,
      salary_currency: /^(salary currency|currency)$/,
      available_date:
        /^(available date|availability date|date available|earliest start date|available start date)$/,
      skills: /^(skills|technical skills|key skills)$/,
      certifications: /^(certifications|professional certifications)$/,
      interests: /^(interests|professional interests)$/,
      'education.institution': /^(school|university|college|institution)( name)?$/,
      'education.degree': /^degree$/,
      'education.field_of_study': /^(major|field of study)$/,
      'education.gpa': /^(gpa|grade point average)$/,
    };
    for (const [key, pattern] of Object.entries(simple)) if (pattern.test(text)) return { key };
    const auto = autocomplete.toLowerCase().trim().split(/\s+/).at(-1);
    if (AUTOCOMPLETE[auto] && !String(label).trim()) return { key: AUTOCOMPLETE[auto] };
    return { key: null };
  }
  const COUNTRY_ALIASES = {
    us: 'united states',
    usa: 'united states',
    'united states of america': 'united states',
    uk: 'united kingdom',
    gb: 'united kingdom',
    'great britain': 'united kingdom',
    ca: 'canada',
    au: 'australia',
    de: 'germany',
    fr: 'france',
    in: 'india',
  };
  const STATE_NAMES =
    'AL:Alabama|AK:Alaska|AZ:Arizona|AR:Arkansas|CA:California|CO:Colorado|CT:Connecticut|DE:Delaware|DC:District of Columbia|FL:Florida|GA:Georgia|HI:Hawaii|ID:Idaho|IL:Illinois|IN:Indiana|IA:Iowa|KS:Kansas|KY:Kentucky|LA:Louisiana|ME:Maine|MD:Maryland|MA:Massachusetts|MI:Michigan|MN:Minnesota|MS:Mississippi|MO:Missouri|MT:Montana|NE:Nebraska|NV:Nevada|NH:New Hampshire|NJ:New Jersey|NM:New Mexico|NY:New York|NC:North Carolina|ND:North Dakota|OH:Ohio|OK:Oklahoma|OR:Oregon|PA:Pennsylvania|RI:Rhode Island|SC:South Carolina|SD:South Dakota|TN:Tennessee|TX:Texas|UT:Utah|VT:Vermont|VA:Virginia|WA:Washington|WV:West Virginia|WI:Wisconsin|WY:Wyoming';
  const STATE_ALIASES = Object.fromEntries(
    STATE_NAMES.split('|').map((pair) => {
      const [a, b] = pair.split(':');
      return [normalize(a), normalize(b)];
    }),
  );
  function selectOption(options, value, key = '') {
    const canonical = (v) => {
      const n = normalize(v);
      return key === 'country'
        ? COUNTRY_ALIASES[n] || n
        : key === 'state'
          ? STATE_ALIASES[n] || n
          : n;
    };
    const boolean = typeof value === 'boolean';
    const target = boolean
      ? value
        ? ['yes', 'true', '1']
        : ['no', 'false', '0']
      : [canonical(value)];
    if (!target[0]) return null;
    const matches = options.filter((option) => {
      if (option.disabled || String(option.value) === '') return false;
      return (
        target.includes(canonical(option.label)) ||
        (!boolean && target.includes(canonical(option.value)))
      );
    });
    return matches.length === 1 ? String(matches[0].value) : null;
  }
  function validateResume(file, bytes) {
    if (!file || !/\.(pdf|docx)$/i.test(file.name || '')) return 'Choose a PDF or DOCX resume.';
    if (!Number.isFinite(file.size) || file.size <= 0 || file.size > MAX_BYTES)
      return 'Resume must be between 1 byte and 5 MiB.';
    const signature = Array.from(bytes || []).slice(0, 5);
    if (
      /\.pdf$/i.test(file.name)
        ? signature.join(',') !== '37,80,68,70,45'
        : signature.slice(0, 4).join(',') !== '80,75,3,4'
    )
      return 'File contents do not match its PDF or DOCX extension.';
    return null;
  }
  return {
    TEXT_FIELDS,
    BOOLEAN_FIELDS,
    LIST_FIELDS,
    RECORD_FIELDS,
    MAX_BYTES,
    normalize,
    sanitizeProfile,
    inferField,
    selectOption,
    validateResume,
  };
});
